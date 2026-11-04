"""The sending service: the only process that holds Airwallex keys, when it is turned on.

    python -m ledgerline.sender            # LEDGERLINE_SENDER_LISTEN=unix:/run/ledgerline-send/send.sock

With LEDGERLINE_SENDER_SOCKET set, the app keeps no Airwallex keys and cannot unseal a company's stored credentials.
For a company connected to Airwallex it holds a proxy instead of a bank client:

- Money-out (a refund, a bill payment, a conversion) is asked for by id only: an approval, payment, quote or payment
  id plus who pressed the button. The sender opens the company's database itself and runs the same code the app would
  have run: approval status and scope hash, expiry, the pause switch, sender different from approver, the duplicate
  lock, the stable request id and the read-back after a timeout. No amount, account or request id is accepted.
- Everything else the app needs from the bank (rates, quotes, transfer status, beneficiaries, deposits, payment
  links, which move no money) is forwarded by method name from a fixed list. `create_transfer` and
  `create_conversion` are never forwarded.

What it does not change: a compromised app could still request a send that its own database says was approved.
The sender checks the database's approval; it cannot know whether that approval was written by a real person.

Requests are one JSON line per connection on a Unix socket that only the app's group can open; the sender also checks
the caller's user id when LEDGERLINE_SENDER_PEER_UID is set. `tcp:127.0.0.1:<port>` exists for tests and Windows
development only, and only on loopback.
"""
from __future__ import annotations

import dataclasses
import functools
import json
import logging
import os
import socket
import socketserver
import struct
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

log = logging.getLogger("ledgerline.sender")
MAX_LINE = 1 << 20
TIMEOUT = 90.0  # a send can wait on Airwallex; the client gives up later than the provider does

# Forwarded to the bank client by name. None of these moves money.
PROXY_METHODS = frozenset({
    "readiness", "current_rate", "list_deposits", "beneficiary_schema", "validate_beneficiary", "create_beneficiary",
    "list_beneficiaries", "simulate_deposit", "get_deposit", "find_transfer", "get_transfer", "simulate_transfer_status",
    "create_quote", "get_conversion", "find_conversion", "create_payment_link", "payment_link_paid",
})
NEVER_FORWARDED = frozenset({"create_transfer", "create_conversion"})


class SenderUnavailable(RuntimeError):
    """The sending service could not be reached. Nothing was sent."""


class SenderRefused(ValueError):
    """The sending service refused a request that is not allowed."""


# --------------------------------------------------------------------------- wire format
def _encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {"__type__": type(value).__name__, **{k: _encode(v) for k, v in dataclasses.asdict(value).items()}}
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    from .providers import base

    if isinstance(value, list):
        return [_decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    if "__decimal__" in value:
        return Decimal(value["__decimal__"])
    if "__datetime__" in value:
        return datetime.fromisoformat(value["__datetime__"])
    fields = {k: _decode(v) for k, v in value.items() if k != "__type__"}
    kind = value.get("__type__")
    if kind in ("TransferResult", "Quote", "ConversionResult", "PaymentLinkResult"):
        return getattr(base, kind)(**fields)
    return fields


def _errors() -> dict[str, type[BaseException]]:
    """Exceptions that cross the socket keep their type, so the app answers exactly as it does without a sender."""
    from .control import AuthError
    from .payouts import Paused, PayoutError, PracticeOnly, SelfApproval, StaleApproval
    from .providers.base import ProviderAmbiguous, ProviderError, ProviderUnsupported
    from .treasury import TreasuryError

    kinds = (Paused, PayoutError, PracticeOnly, SelfApproval, StaleApproval, TreasuryError, ProviderError, ProviderAmbiguous,
             ProviderUnsupported, SenderRefused, ValueError, KeyError)
    out: dict[str, type[BaseException]] = {k.__name__: k for k in kinds}
    out["AuthError"] = AuthError
    return out


def _parse_address(address: str) -> tuple[str, Any]:
    if address.startswith("unix:"):
        return "unix", address[5:]
    if address.startswith("tcp:"):
        host, _, port = address[4:].rpartition(":")
        if host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
            raise ValueError("the sender's tcp address is for tests and must be loopback")
        return "tcp", (host.strip("[]"), int(port))
    raise ValueError("sender address must start with unix: or tcp:")


# --------------------------------------------------------------------------- client side (the app)
class SenderClient:
    def __init__(self, address: str, timeout: float = TIMEOUT) -> None:
        self.kind, self.target = _parse_address(address)
        self.timeout = timeout

    def call(self, method: str, org_id: str, **params: Any) -> Any:
        family = socket.AF_UNIX if self.kind == "unix" else socket.AF_INET  # type: ignore[attr-defined]
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(self.target)
                s.sendall(json.dumps({"method": method, "org_id": org_id, **_encode(params)}).encode() + b"\n")
                with s.makefile("rb") as f:
                    line = f.readline(MAX_LINE)
        except OSError as exc:
            raise SenderUnavailable(f"the sending service is not reachable ({type(exc).__name__}); nothing was sent") from None
        if not line:
            raise SenderUnavailable("the sending service closed the connection; check the operation before trying again")
        reply = json.loads(line)
        if reply.get("ok"):
            return _decode(reply.get("result"))
        kind = _errors().get(reply.get("error", ""), SenderRefused)
        if kind.__name__ == "AuthError":
            raise kind(int(reply.get("status", 403)), reply.get("message", ""))
        raise kind(reply.get("message", "refused by the sending service"))


class SenderProxy:
    """Stands in for a company's bank client in the app. Reads go through by name; sending money never does."""

    name = "airwallex_sandbox"
    label = "AIRWALLEX SANDBOX (test environment, no real money)"

    def __init__(self, client: SenderClient, org_id: str) -> None:
        self._client, self._org_id = client, org_id

    def __getattr__(self, method: str) -> Callable[..., Any]:
        if method in NEVER_FORWARDED:
            raise SenderRefused(f"{method} runs only inside the sending service, behind its own checks")
        if method not in PROXY_METHODS:
            raise AttributeError(method)
        return lambda *args, **kwargs: self._client.call("provider", self._org_id, op=method, args=list(args), kwargs=kwargs)


def through_sender(method: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """For a money-out function taking (ctx, ids..., actor): when the app has a sending service, ask it by id instead."""
    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def inner(ctx: Any, *args: Any, **kwargs: Any) -> Any:
            client = getattr(ctx, "sender", None)
            if client is None:
                return fn(ctx, *args, **kwargs)
            return client.call(method, ctx.org["id"], args=list(args), kwargs=kwargs)
        return inner
    return wrap


# --------------------------------------------------------------------------- server side (the sending service)
def _money_out() -> dict[str, Callable[..., Any]]:
    from . import bill_payments, payouts, treasury, wrong_currency

    return {
        "send_refund": payouts.execute_refund,
        "send_bill_payment": bill_payments.execute,
        "execute_conversion": treasury.execute_conversion,
        "convert_deposit": wrong_currency.convert,
    }


def _plain(values: Any) -> bool:
    """Ids, actors and flags only: no structures, so no amount, account or request id can be passed in."""
    return all(v is None or isinstance(v, (str, bool, int)) for v in values)


class Service:
    def __init__(self, settings: Any, peer_uid: int | None = None) -> None:
        from .clock import Clock
        from .control import ControlPlane

        self.settings = dataclasses.replace(settings, sender_socket=None)  # the service itself always talks to the bank
        self.clock = Clock()
        self.control = ControlPlane(settings.pg_target("control") if settings.postgres else settings.data_dir / "control.sqlite3", self.clock)
        self.peer_uid = peer_uid
        self._contexts: dict[str, Any] = {}
        self._lock = threading.Lock()

    def context(self, org_id: str) -> Any:
        from .tenancy import build_org_context

        with self._lock:
            org = self.control.org(org_id)
            if org is None:
                raise KeyError("unknown organization")
            if org.get("bank_mode") != "airwallex_sandbox":
                raise SenderRefused("this organization is not connected to Airwallex")
            ctx = self._contexts.get(org_id)
            stamp = (org.get("airwallex_credentials_enc"), self.settings.sandbox_allowed(org_id))
            if ctx is None or getattr(ctx, "_sender_stamp", None) != stamp:  # rebuilt if the connection changed
                ctx = build_org_context(self.settings, org, self.clock)
                ctx._sender_stamp = stamp
                self._contexts[org_id] = ctx
            return ctx

    def handle(self, request: dict[str, Any]) -> Any:
        method, org_id = request.get("method"), request.get("org_id")
        if method == "seal":
            from .connections import seal

            return seal(self.settings, str(org_id), str(request["client_id"]), str(request["api_key"]))
        if method == "server_readiness":
            from .providers.airwallex import AirwallexSandbox

            if not self.settings.airwallex_configured:
                return {"configured": False}
            return AirwallexSandbox(self.settings.airwallex_client_id, self.settings.airwallex_api_key, timeout=10).readiness()
        if not isinstance(org_id, str):
            raise SenderRefused("organization id missing")
        args, kwargs = _decode(request.get("args") or []), _decode(request.get("kwargs") or {})
        if method == "provider":
            op = request.get("op")
            if op not in PROXY_METHODS:
                raise SenderRefused(f"{op} is not something the app may ask the bank for")
            return getattr(self.context(org_id).sandbox, op)(*args, **kwargs)
        fn = _money_out().get(str(method))
        if fn is None:
            raise SenderRefused(f"unknown request {method!r}")
        if not isinstance(args, list) or not isinstance(kwargs, dict) or not _plain(args) or not _plain(kwargs.values()):
            raise SenderRefused("money-out requests take ids only")
        return fn(self.context(org_id), *args, **kwargs)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        service: Service = self.server.service  # type: ignore[attr-defined]
        if service.peer_uid is not None and hasattr(socket, "SO_PEERCRED"):
            _pid, uid, _gid = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            if uid != service.peer_uid:
                log.warning("refused a connection from uid %s", uid)
                return
        line = self.rfile.readline(MAX_LINE)
        try:
            reply = {"ok": True, "result": _encode(service.handle(json.loads(line)))}
        except Exception as exc:  # noqa: BLE001 - every failure goes back to the app with its type
            status = getattr(exc, "status", None)
            reply = {"ok": False, "error": type(exc).__name__, "message": str(exc).strip("'\""), "status": status}
            if type(exc).__name__ not in _errors() and not isinstance(exc, (ValueError, KeyError)):
                log.exception("sender request failed")
        self.wfile.write(json.dumps(reply).encode() + b"\n")


def serve(settings: Any, address: str, peer_uid: int | None = None) -> socketserver.BaseServer:
    """Start serving in the calling thread's process. Returns the server; call serve_forever() or shutdown()."""
    kind, target = _parse_address(address)
    if kind == "unix":
        if os.path.exists(target):
            os.unlink(target)
        server: Any = socketserver.ThreadingUnixStreamServer(target, _Handler)  # type: ignore[attr-defined]
        os.chmod(target, 0o660)  # the app's group may connect; nobody else
    else:
        server = socketserver.ThreadingTCPServer(target, _Handler)
    server.daemon_threads = True
    server.service = Service(settings, peer_uid)
    return server


def main() -> None:
    from .config import load_settings

    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    address = os.environ.get("LEDGERLINE_SENDER_LISTEN", "unix:/run/ledgerline-send/send.sock")
    uid = os.environ.get("LEDGERLINE_SENDER_PEER_UID")
    server = serve(settings, address, int(uid) if uid else None)
    log.info("sending service listening on %s", address)
    server.serve_forever()


if __name__ == "__main__":
    main()
