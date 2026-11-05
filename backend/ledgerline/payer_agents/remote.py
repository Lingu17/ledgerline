"""Calling a customer's own payer agent over the network.

The URL comes from a customer record, so every call is treated as untrusted outbound traffic:

- https only. Plain http is allowed only for loopback, and only when LEDGERLINE_PAYER_AGENT_ALLOW_LOOPBACK is set
  (local development and tests). The hosted app never sets it.
- The host is resolved at connect time and every address it resolves to must be public: private, loopback,
  link-local (including the cloud metadata address), shared, reserved, multicast and unspecified addresses are
  refused. The connection is then made to the checked address, so a second DNS answer cannot swap it.
- Redirects to another origin are never followed (the MCP client follows only same-origin ones, and those pass
  the same connect-time check).
- Connect and read timeouts, an overall deadline, and a cap on the bytes read per connection.
- No credentials, cookies or proxy settings from the environment are sent.

An agent's answer is still only a claim: it goes through the same three checks as any other.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import typing
from urllib.parse import urlsplit

import anyio
import httpcore2
import httpx2
from httpcore2._backends.auto import AutoBackend
from httpcore2._backends.base import AsyncNetworkBackend, AsyncNetworkStream
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

MAX_URL_LENGTH = 300
MAX_RESPONSE_BYTES = 256 * 1024
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
OVERALL_DEADLINE = 25.0
_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}


class AgentRefused(ValueError):
    """The agent URL or the address it resolves to is not allowed."""


class AgentUnreachable(RuntimeError):
    """The agent could not be called or did not answer in time."""


def check_url(url: typing.Any, allow_loopback: bool = False) -> str:
    """Shape checks on a registered agent URL. The address check happens again at connect time."""
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_URL_LENGTH:
        raise AgentRefused(f"agent URL must be text of at most {MAX_URL_LENGTH} characters")
    url = url.strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")  # "localhost." and "2130706433." are the same hosts
    if parts.username or parts.password:
        raise AgentRefused("agent URL must not contain a user name or password")
    if parts.fragment:
        raise AgentRefused("agent URL must not contain a fragment")
    if not host:
        raise AgentRefused("agent URL needs a host")
    if parts.scheme == "https":
        pass
    elif parts.scheme == "http" and allow_loopback and host in _LOOPBACK_NAMES:
        pass
    else:
        raise AgentRefused("agent URL must start with https://")
    try:
        _ = parts.port
    except ValueError as exc:
        raise AgentRefused("agent URL has an invalid port") from exc
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is None and all(re.fullmatch(r"0x[0-9a-f]+|[0-9]+", label) for label in host.split(".")):
        # 2130706433, 0177.0.0.1 or 0x7f.1 are addresses in disguise; the connect-time check refuses them too.
        raise AgentRefused("agent URL must use a host name or a plain dotted IP address")
    if literal is not None and not address_allowed(literal, allow_loopback):
        raise AgentRefused(f"agent URL points to a non-public address ({host})")
    if host in ("localhost",) and not allow_loopback:
        raise AgentRefused("agent URL points to this server (localhost)")
    return url


_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


def address_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_loopback: bool = False) -> bool:
    """Public addresses only. An IPv4 address carried inside an IPv6 one (mapped, NAT64, 6to4, Teredo) is checked too."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in _NAT64_LOCAL:
            return False
        embedded = [ip.ipv4_mapped, ip.sixtofour, *(ip.teredo or ()),
                    ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF) if ip in _NAT64 else None]
        embedded = [e for e in embedded if e is not None]
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif any(not address_allowed(e, allow_loopback) for e in embedded):
            return False
    if allow_loopback and ip.is_loopback:
        return True
    return ip.is_global and not ip.is_multicast


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AgentUnreachable(f"cannot resolve {host}") from exc
    return list(dict.fromkeys(info[4][0] for info in infos))


class _CappedStream(AsyncNetworkStream):
    """Counts every byte read on the connection, including after TLS starts, and stops at the cap."""

    def __init__(self, inner: AsyncNetworkStream, budget: list[int]) -> None:
        self._inner, self._budget = inner, budget

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        data = await self._inner.read(max_bytes, timeout)
        self._budget[0] -= len(data)
        if self._budget[0] < 0:
            raise httpcore2.ReadError(f"agent response is larger than {MAX_RESPONSE_BYTES} bytes")
        return data

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        await self._inner.write(buffer, timeout)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def start_tls(self, ssl_context, server_hostname: str | None = None, timeout: float | None = None) -> AsyncNetworkStream:
        return _CappedStream(await self._inner.start_tls(ssl_context, server_hostname, timeout), self._budget)

    def get_extra_info(self, info: str) -> typing.Any:
        return self._inner.get_extra_info(info)


class _GuardedBackend(AsyncNetworkBackend):
    """Resolves the host itself, refuses non-public addresses, and connects to the address it checked."""

    def __init__(self, allow_loopback: bool, resolve: typing.Callable[[str, int], list[str]] = _resolve) -> None:
        self._inner, self._allow_loopback, self._resolve = AutoBackend(), allow_loopback, resolve

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None,
                          socket_options: typing.Iterable[typing.Any] | None = None) -> AsyncNetworkStream:
        addresses = await anyio.to_thread.run_sync(self._resolve, host, port)
        refused = [a for a in addresses if not address_allowed(ipaddress.ip_address(a.split("%")[0]), self._allow_loopback)]
        if refused or not addresses:
            raise AgentRefused(f"{host} resolves to a non-public address; not calling it")
        stream = await self._inner.connect_tcp(addresses[0], port, timeout=timeout, socket_options=socket_options)
        return _CappedStream(stream, [MAX_RESPONSE_BYTES])

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None) -> AsyncNetworkStream:
        raise AgentRefused("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


async def _drop_cookies(request: httpx2.Request) -> None:
    request.headers.pop("cookie", None)
    request.headers.pop("authorization", None)


def guarded_http_client(allow_loopback: bool = False, resolve=None) -> httpx2.AsyncClient:
    transport = httpx2.AsyncHTTPTransport(trust_env=False, retries=0)
    # Same TLS settings as httpx2's own pool, but every connection goes through the guarded backend.
    transport._pool = httpcore2.AsyncConnectionPool(  # noqa: SLF001 - httpx2 has no public hook for the network backend
        ssl_context=transport._pool._ssl_context, max_connections=4, max_keepalive_connections=0,  # noqa: SLF001
        network_backend=_GuardedBackend(allow_loopback, resolve or _resolve))
    return httpx2.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                              timeout=httpx2.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
                              headers={"user-agent": "Ledgerline payer-agent client"},
                              event_hooks={"request": [_drop_cookies]})


def _parse(result: typing.Any) -> dict[str, typing.Any]:
    from .client import _parse_result

    return _parse_result(result)


async def _call(url: str, requests: list[dict[str, typing.Any]], allow_loopback: bool, resolve, deadline: float) -> list[dict[str, typing.Any]]:
    out = []
    with anyio.fail_after(deadline):
        async with guarded_http_client(allow_loopback, resolve) as http:
            async with Client(streamable_http_client(url, http_client=http, terminate_on_close=False), read_timeout_seconds=READ_TIMEOUT) as client:
                tools = await client.list_tools()
                if "explain_payment" not in {t.name for t in tools.tools}:
                    raise AgentUnreachable("the agent does not offer explain_payment")
                for req in requests:
                    result = await client.call_tool("explain_payment", req)
                    out.append({"status": "error", "detail": "the agent reported an error"} if getattr(result, "is_error", False) else _parse(result))
    return out


def ask_remote(url: str, requests: list[dict[str, typing.Any]], allow_loopback: bool = False, resolve=None,
               deadline: float | None = None) -> list[dict[str, typing.Any]]:
    """Ask one customer's own agent. Raises AgentRefused for a URL or address that is not allowed, and AgentUnreachable
    when the agent cannot be reached or answers badly; the caller leaves the payment waiting in either case."""
    url = check_url(url, allow_loopback)
    try:
        return anyio.run(_call, url, requests, allow_loopback, resolve, min(deadline or OVERALL_DEADLINE, OVERALL_DEADLINE))
    except AgentRefused:
        raise
    except BaseException as exc:  # noqa: BLE001 - network, protocol and timeout errors all mean "no answer this time"
        refused = _find(exc, AgentRefused)
        if refused is not None:
            raise refused from None
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise AgentUnreachable(_describe(exc)) from None


def _find(exc: BaseException, kind: type[BaseException]) -> BaseException | None:
    """Exception groups from task groups can wrap the real cause; look through them and through causes."""
    seen, todo = set(), [exc]
    while todo:
        e = todo.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, kind):
            return e
        todo += list(getattr(e, "exceptions", ()) or ())
        todo += [x for x in (e.__cause__, e.__context__) if x is not None]
    return None


def _describe(exc: BaseException) -> str:
    if _find(exc, TimeoutError) is not None or _find(exc, httpx2.TimeoutException) is not None:
        return "the agent did not answer in time"
    if _find(exc, httpcore2.ReadError) is not None and "larger than" in str(_find(exc, httpcore2.ReadError)):
        return f"the agent's response was larger than {MAX_RESPONSE_BYTES} bytes"
    return f"could not reach the agent ({type(exc).__name__})"
