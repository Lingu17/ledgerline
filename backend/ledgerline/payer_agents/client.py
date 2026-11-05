"""MCP client used by Ledgerline to call payer agents' explain_payment tool."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import anyio
from mcp import Client, StdioServerParameters

from ..config import BACKEND_DIR


def _parse_result(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured["result"] if set(structured) == {"result"} else structured
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise ValueError("payer agent returned no content")


async def _call_all(target: Any, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    async with Client(target, read_timeout_seconds=30) as client:
        tools = await client.list_tools()
        if "explain_payment" not in {t.name for t in tools.tools}:
            raise RuntimeError("payer MCP server does not expose explain_payment")
        for req in requests:
            result = await client.call_tool("explain_payment", req)
            if getattr(result, "is_error", False):
                out.append({"status": "error", "detail": str(getattr(result, "content", ""))})
            else:
                out.append(_parse_result(result))
    return out


QUESTION_FIELDS = ("customer_id", "deposit_id", "currency", "amount_minor", "received_at", "reference")
# One organization's own agents must not hold up anyone else: each round gets a time budget, the rest waits for the next
# round, and an agent that keeps failing is left alone for a while.
ROUND_BUDGET = 30.0
BACKOFF_AFTER, BACKOFF_SECONDS = 3, 600
_failures: dict[tuple[str, str], tuple[int, float]] = {}  # keyed by (organization, URL): one cannot back off another
_failures_lock = threading.Lock()
_STDIO_SLOTS = threading.BoundedSemaphore(3)


def _backed_off(url: tuple[str, str]) -> float | None:
    with _failures_lock:
        count, until = _failures.get(url, (0, 0.0))
    return until if count >= BACKOFF_AFTER and time.monotonic() < until else None


def _record(url: tuple[str, str], ok: bool) -> None:
    with _failures_lock:
        if ok:
            _failures.pop(url, None)
            return
        count = _failures.get(url, (0, 0.0))[0] + 1
        _failures[url] = (count, time.monotonic() + BACKOFF_SECONDS if count >= BACKOFF_AFTER else 0.0)


def agent_label(transport: str) -> str:
    """How an answer's source reads on screen: the customer's own agent, or a simulated one on this server."""
    return "Customer's own agent" if transport.startswith("mcp/http") else "Simulated agent"


def ask_agents(ctx, questions: list[dict[str, Any]], simulated=None) -> list[tuple[dict[str, Any], dict[str, Any] | None, str, str | None]]:
    """Ask each payer's agent. A customer that registered its own agent is asked at its URL over the network; the rest
    go to the simulated agents on this server. Returns (question, answer, transport, problem) in question order. When a
    customer's own agent cannot be asked, answer is None and problem says why: the payment simply stays waiting.
    Errors from the simulated agents propagate, as before."""
    from urllib.parse import urlsplit

    from .. import db
    from . import remote
    from .keys import key_location

    simulated = simulated or explain_payments
    with ctx.conn() as conn:
        urls = {r["id"]: r["agent_url"] for r in db.rows(conn, "SELECT id, agent_url FROM customers WHERE agent_url IS NOT NULL")}
    out: list[Any] = [None] * len(questions)
    by_url: dict[str, list[int]] = {}
    for i, q in enumerate(questions):
        if q["customer_id"] in urls:
            by_url.setdefault(urls[q["customer_id"]], []).append(i)
    local = [i for i, q in enumerate(questions) if q["customer_id"] not in urls]
    if local:
        # Practice companies ask the simulated agents in-process over the same MCP protocol: a process per question
        # capped the server at about 30 judges at once. Real companies keep the separate process.
        transport = "memory" if (ctx.org or {}).get("kind") == "sample" else ctx.settings.payer_mcp_transport
        answers, label = simulated(key_location(ctx.settings), [questions[i] for i in local], transport)
        for i, a in zip(local, answers):
            out[i] = (questions[i], a, label, None)
    started = time.monotonic()
    org_key = (ctx.org or {}).get("id", "")
    for url, idxs in by_url.items():
        label = f"mcp/http {urlsplit(url).hostname}"
        remaining = ROUND_BUDGET - (time.monotonic() - started)
        skip = None
        if remaining < 1:
            skip = "not asked this round: this organization's time for asking its customers' agents is used up; asked next round"
        elif _backed_off((org_key, url)) is not None:
            skip = f"not asked: this agent failed {BACKOFF_AFTER} times in a row, so it is left alone for {BACKOFF_SECONDS // 60} minutes"
        if skip:
            for i in idxs:
                out[i] = (questions[i], None, label, skip)
            continue
        # Only what the question needs leaves this server: no balances, notes or other customers' data.
        reqs = [{k: questions[i][k] for k in QUESTION_FIELDS} for i in idxs]
        try:
            answers = remote.ask_remote(url, reqs, ctx.settings.payer_agent_allow_loopback, deadline=remaining)
            if len(answers) != len(idxs):
                raise remote.AgentUnreachable("the agent answered a different number of questions")
            _record((org_key, url), True)
            for i, a in zip(idxs, answers):
                out[i] = (questions[i], a if isinstance(a, dict) else {"status": "error", "detail": "answer is not an object"}, label, None)
        except (remote.AgentRefused, remote.AgentUnreachable) as exc:
            _record((org_key, url), False)
            for i in idxs:
                out[i] = (questions[i], None, label, str(exc))
    return out


def explain_payments(
    data_dir, requests: list[dict[str, Any]], transport: str = "stdio"
) -> tuple[list[dict[str, Any]], str]:
    """Call explain_payment for each request over one MCP session. Returns (answers, transport label)."""
    if not requests:
        return [], "none"
    if transport == "memory":
        from .keys import EnvKeys, PgKeys, load_keys
        from .server import build_server

        # Decrypt here, as the stdio path does: a key that cannot be decrypted (wrong LEDGERLINE_SECRET_KEY) raises in
        # this process and the payment stays waiting, instead of becoming a tool error recorded as a rejected answer.
        target: Any = build_server(EnvKeys(load_keys(data_dir)) if isinstance(data_dir, PgKeys) else data_dir)
        label = "mcp/in-memory"
    else:
        from mcp.client.stdio import get_default_environment

        from .keys import PgKeys, load_keys

        if isinstance(data_dir, PgKeys):
            env = {**get_default_environment(), "LEDGERLINE_AGENT_KEYS": json.dumps(load_keys(data_dir))}
            args = ["-m", "ledgerline.payer_agents.server"]
        else:
            env, args = None, ["-m", "ledgerline.payer_agents.server", "--data-dir", str(data_dir)]
        target = StdioServerParameters(command=sys.executable, args=args, cwd=str(BACKEND_DIR), env=env)
        label = "mcp/stdio"
        with _STDIO_SLOTS:  # each call starts a process (about 1 s of CPU and 50 MB): at most three at once
            return anyio.run(_call_all, target, requests), label
    return anyio.run(_call_all, target, requests), label
