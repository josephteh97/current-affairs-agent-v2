"""
MCP agent tools server
Exposes: web_search, write_essay
Run: python mcp.py
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Agent MCP Server")
