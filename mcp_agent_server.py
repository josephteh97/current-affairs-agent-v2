"""
mcp_agent_server.py — ARIA MCP Tool Server

Exposes all agent tools over the MCP protocol so any MCP-compatible client
(Claude Desktop, etc.) can use them.

All tool logic lives in tools.py — this file only handles MCP registration.

Run: ./run.sh mcp   OR   python mcp_agent_server.py
"""

import functools
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from tool_gate import SPECS, ToolGate

mcp = FastMCP(name="ARIA MCP Server")

# The MCP server has no terminal to ask in, so write tools are denied unless the
# operator opts in with ARIA_MCP_ALLOW_WRITES=1 — in that case the MCP client's
# own per-call approval prompt is the human check. No per-turn budget: MCP has
# no notion of a turn (the client drives the loop).
_allow_writes = os.getenv("ARIA_MCP_ALLOW_WRITES") == "1"
_gate = ToolGate(confirm=(lambda name, args: True) if _allow_writes else None, budget=None)


def _guarded(name: str):
    fn = SPECS[name].fn

    @functools.wraps(fn)  # keeps the signature, so FastMCP builds the same schema
    def wrapper(**kwargs):
        return _gate.call(name, kwargs)[0]
    return wrapper


# Register every shared tool through the gate
for _name in SPECS:
    mcp.tool()(_guarded(_name))


# ── MCP-only tool: remember_context ──────────────────────────────────────────
# This tool is specific to the MCP interface (conversational key-value memory).
# It is not used by agent.py, which has its own RL-based memory system.

@mcp.tool()
def remember_context(key: str, value: str) -> str:
    """Store a piece of information for later reference in the conversation.
    Writes to a simple key-value store in memory.md.
    """
    import re
    memory_file = Path(__file__).parent / "memory.md"
    try:
        existing = memory_file.read_text() if memory_file.exists() else ""
        pattern  = rf"^## {re.escape(key)}\n.*?(?=^## |\Z)"
        new_entry = f"## {key}\n{value}\n\n"
        if re.search(pattern, existing, flags=re.MULTILINE | re.DOTALL):
            updated = re.sub(pattern, new_entry, existing, flags=re.MULTILINE | re.DOTALL)
        else:
            updated = existing + new_entry
        memory_file.write_text(updated)
        return f"Stored: {key} = {value[:100]}..."
    except Exception as e:
        return f"Memory error: {e}"


if __name__ == "__main__":
    print("Starting ARIA MCP Tool Server ...")
    mcp.run()
