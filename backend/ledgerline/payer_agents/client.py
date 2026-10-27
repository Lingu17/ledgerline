"""MCP client used by Ledgerline to call payer agents' explain_payment tool."""
from __future__ import annotations

import json
import sys
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


def explain_payments(
    data_dir, requests: list[dict[str, Any]], transport: str = "stdio"
) -> tuple[list[dict[str, Any]], str]:
    """Call explain_payment for each request over one MCP session. Returns (answers, transport label)."""
    if not requests:
        return [], "none"
    if transport == "memory":
        from .server import build_server

        target: Any = build_server(data_dir)
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
    return anyio.run(_call_all, target, requests), label
