"""
mcp_agent_server.py — ARIA MCP Tool Server

Exposes all agent tools over the MCP protocol so any MCP-compatible client
(Claude Desktop, etc.) can use them.

All tool logic lives in tools.py — this file only handles MCP registration.

Run: ./run.sh mcp   OR   python mcp_agent_server.py
"""

import functools
import json
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from tool_gate import SPECS, AuditLog, Spec, Match, Str, ToolGate
from tools import AUDIT_LOG, DATA_DIR

mcp = FastMCP(name="ARIA MCP Server")

MEMORY_FILE = DATA_DIR / "memory.json"
MAX_MEMORY_KEYS = 100


# ── MCP-only tool: remember_context ──────────────────────────────────────────
# Specific to the MCP interface (conversational key-value memory); agent.py has
# its own RL-based memory. Stored as JSON, so a value can never forge or
# overwrite another key (the old regex-edited memory.md could be).

def remember_context(key: str, value: str) -> str:
    """Store a piece of information for later reference in the conversation.
    key: lowercase letters, digits and underscores (max 40). value: max 2000 chars.
    """
    try:
        memory = json.loads(MEMORY_FILE.read_text()) if MEMORY_FILE.exists() else {}
        if key not in memory and len(memory) >= MAX_MEMORY_KEYS:
            return f"Memory full ({MAX_MEMORY_KEYS} keys). Overwrite an existing key instead."
        memory[key] = value
        MEMORY_FILE.write_text(json.dumps(memory, indent=2, ensure_ascii=False))
        return f"Stored: {key} = {value[:100]}"
    except Exception as e:
        return f"Memory error: {e}"


MCP_SPECS = {
    **SPECS,
    "remember_context": Spec(remember_context, "write", {
        "key": Match(r"[a-z0-9_]{1,40}"), "value": Str(2000),
    }, required=("key", "value")),
}

# The MCP server has no terminal to ask in, so write tools are denied unless the
# operator opts in with ARIA_MCP_ALLOW_WRITES=1 — in that case the MCP client's
# own per-call approval prompt is the human check. No per-turn budget or URL
# provenance: MCP has no notion of a turn, and the server never sees the user's
# message (the client drives the loop and approves each call).
_allow_writes = os.getenv("ARIA_MCP_ALLOW_WRITES") == "1"
_gate = ToolGate(confirm=(lambda name, args, reason: True) if _allow_writes else None,
                 budget=None, provenance=False, specs=MCP_SPECS,
                 audit=AuditLog(AUDIT_LOG, host="mcp"))


def _guarded(name: str):
    fn = MCP_SPECS[name].fn

    @functools.wraps(fn)  # keeps the signature, so FastMCP builds the same schema
    def wrapper(**kwargs):
        return _gate.call(name, kwargs)[0]
    return wrapper


# Every tool is registered through the gate — nothing reaches the model unguarded.
for _name in MCP_SPECS:
    mcp.tool(name=_name)(_guarded(_name))  # tool name = registry key, not fn.__name__


if __name__ == "__main__":
    print("Starting ARIA MCP Tool Server ...")
    mcp.run()
