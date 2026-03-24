#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run.sh — ARIA Agent launcher
#
# Usage:
#   ./run.sh              — start the agent (default model: llama3.1:8b)
#   ./run.sh --debug      — start with debug output
#   ./run.sh --model llama3.2
#   ./run.sh --model llama3.2 --debug
#   ./run.sh mcp          — start the MCP tool server instead
#   ./run.sh install      — install Python dependencies
#   ./run.sh check        — check all dependencies without starting
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
RST='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { echo -e "${BLU}[INFO]${RST}  $*"; }
ok()    { echo -e "${GRN}[ OK ]${RST}  $*"; }
warn()  { echo -e "${YLW}[WARN]${RST}  $*"; }
error() { echo -e "${RED}[ERR ]${RST}  $*"; }

# ── Find Python ───────────────────────────────────────────────────────────────
find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            ver=$("$cmd" -c "import sys; print(sys.version_info[:2])")
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    error "Python 3.10+ is required but not found."
    error "Install it from https://python.org or via your package manager."
    exit 1
}

PYTHON=$(find_python)

# ── Subcommand: install ───────────────────────────────────────────────────────
cmd_install() {
    info "Installing Python dependencies from requirements.txt ..."
    "$PYTHON" -m pip install -r requirements.txt
    ok "Dependencies installed."
}

# ── Subcommand: check ─────────────────────────────────────────────────────────
cmd_check() {
    echo ""
    echo -e "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
    echo -e "${CYN}  ARIA — Dependency Check${RST}"
    echo -e "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
    echo ""

    # Python version
    pyver=$("$PYTHON" --version 2>&1)
    ok "Python: $pyver ($PYTHON)"

    # ddgs / duckduckgo-search
    if "$PYTHON" -c "from ddgs import DDGS" 2>/dev/null; then
        ok "ddgs: installed"
    elif "$PYTHON" -c "from duckduckgo_search import DDGS" 2>/dev/null; then
        ok "duckduckgo-search: installed (ddgs alias)"
    else
        error "ddgs not found — run: ./run.sh install"
        MISSING=1
    fi

    # fastmcp (for mcp_agent_server.py) — check outside project dir to avoid name shadowing
    if "$PYTHON" -c "import sys, importlib.util; spec=importlib.util.find_spec('mcp'); print(spec.origin)" 2>/dev/null | grep -v "mcp_agent_server" >/dev/null 2>&1; then
        ok "fastmcp / mcp: installed"
    else
        warn "fastmcp not found — MCP server (mcp_agent_server.py) will not work"
        warn "Run: ./run.sh install"
    fi

    # sqlite3 (stdlib)
    if "$PYTHON" -c "import sqlite3" 2>/dev/null; then
        ok "sqlite3: available (stdlib)"
    else
        error "sqlite3 missing from Python stdlib — reinstall Python"
        MISSING=1
    fi

    # Ollama
    echo ""
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        models=$(curl -sf http://localhost:11434/api/tags | "$PYTHON" -c \
            "import json,sys; d=json.load(sys.stdin); print(', '.join(m['name'] for m in d.get('models',[])))")
        ok "Ollama: running — models: ${models:-none pulled yet}"
    else
        warn "Ollama: not running (start with: ollama serve)"
        warn "Download Ollama from: https://ollama.com"
    fi

    # Skills dir
    if [ -d "$SCRIPT_DIR/skills" ]; then
        count=$(ls "$SCRIPT_DIR/skills"/*.md 2>/dev/null | wc -l)
        ok "skills/: $count skill file(s) found"
    else
        warn "skills/ directory missing — create it and add skill .md files"
    fi

    echo ""
    if [ "${MISSING:-0}" = "1" ]; then
        error "Some required dependencies are missing. Run: ./run.sh install"
        exit 1
    else
        ok "All required dependencies satisfied."
    fi
    echo ""
}

# ── Subcommand: mcp ───────────────────────────────────────────────────────────
cmd_mcp() {
    info "Starting ARIA MCP Tool Server (mcp_agent_server.py) ..."
    if ! "$PYTHON" -c "import sys; sys.path.insert(0,'/tmp'); import mcp" 2>/dev/null; then
        if ! "$PYTHON" -c "import importlib.util; assert importlib.util.find_spec('mcp') is not None" 2>/dev/null; then
            error "fastmcp not installed. Run: ./run.sh install"
            exit 1
        fi
    fi
    exec "$PYTHON" mcp_agent_server.py
}

# ── Main: start agent ─────────────────────────────────────────────────────────
cmd_agent() {
    # Quick dependency pre-flight
    if ! "$PYTHON" -c "from ddgs import DDGS" 2>/dev/null && \
       ! "$PYTHON" -c "from duckduckgo_search import DDGS" 2>/dev/null; then
        error "ddgs not installed. Run: ./run.sh install"
        exit 1
    fi

    # Check Ollama is up before handing off to agent.py
    if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        warn "Ollama doesn't appear to be running."
        warn "Start it in another terminal with:  ollama serve"
        echo ""
        read -rp "  Continue anyway? [y/N] " ans
        [[ "${ans,,}" == "y" ]] || exit 0
    fi

    echo ""
    exec "$PYTHON" agent.py "$@"
}

# ── Entrypoint ────────────────────────────────────────────────────────────────
case "${1:-}" in
    install)          cmd_install ;;
    check)            cmd_check ;;
    mcp)              shift; cmd_mcp "$@" ;;
    -h|--help|help)
        echo ""
        echo -e "${CYN}Usage:${RST}"
        echo "  ./run.sh                       Start the ARIA agent"
        echo "  ./run.sh --model llama3.2      Use a different Ollama model"
        echo "  ./run.sh --debug               Enable debug output"
        echo "  ./run.sh mcp                   Start the MCP tool server"
        echo "  ./run.sh install               Install Python dependencies"
        echo "  ./run.sh check                 Check all dependencies"
        echo ""
        ;;
    *)                cmd_agent "$@" ;;
esac
