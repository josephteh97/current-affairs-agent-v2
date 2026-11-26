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
    info "Installing Python dependencies from requirements.txt (hash-verified) ..."
    # --require-hashes: pip refuses any file whose SHA-256 differs from the lock,
    # so a swapped or tampered package on the index cannot be installed.
    "$PYTHON" -m pip install --require-hashes -r requirements.txt
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

    # ddgs
    if "$PYTHON" -c "from ddgs import DDGS" 2>/dev/null; then
        ok "ddgs: installed"
    else
        error "ddgs not found — run: ./run.sh install"
        MISSING=1
    fi

    # mcp (for mcp_agent_server.py; FastMCP ships inside it) — check outside project dir to avoid name shadowing
    if "$PYTHON" -c "import sys, importlib.util; spec=importlib.util.find_spec('mcp'); print(spec.origin)" 2>/dev/null | grep -v "mcp_agent_server" >/dev/null 2>&1; then
        ok "mcp: installed"
    else
        warn "mcp not found — MCP server (mcp_agent_server.py) will not work"
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

    # skills.lock — skills are prompt code; they load only if their hash matches
    if "$PYTHON" - <<'PY' 2>/dev/null
import hashlib, json, pathlib, sys
lock = json.loads(pathlib.Path("skills.lock").read_text())
bad = [p.name for p in pathlib.Path("skills").glob("*.md")
       if hashlib.sha256(p.read_bytes()).hexdigest() != lock.get(p.name)]
sys.exit(1 if bad else 0)
PY
    then
        ok "skills.lock: all skills match"
    else
        warn "skills.lock: missing or a skill changed — review, then run: ./run.sh lock-skills"
    fi

    # pip-audit — known vulnerabilities in the locked dependencies
    if command -v pip-audit >/dev/null 2>&1; then AUDIT="pip-audit"
    elif command -v uvx >/dev/null 2>&1; then AUDIT="uvx pip-audit"
    else AUDIT=""; fi
    if [ -n "$AUDIT" ]; then
        if $AUDIT -r requirements.txt --require-hashes --disable-pip >/dev/null 2>&1; then
            ok "pip-audit: no known vulnerabilities in requirements.txt"
        else
            error "pip-audit: vulnerabilities found — run: $AUDIT -r requirements.txt --require-hashes --disable-pip"
            MISSING=1
        fi
    else
        warn "pip-audit not available (pip install pip-audit, or install uv) — dependency CVEs not checked"
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
            error "mcp not installed. Run: ./run.sh install"
            exit 1
        fi
    fi
    exec "$PYTHON" mcp_agent_server.py
}

# ── Main: start agent ─────────────────────────────────────────────────────────
cmd_agent() {
    # Quick dependency pre-flight
    if ! "$PYTHON" -c "from ddgs import DDGS" 2>/dev/null; then
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

cmd_docker() {
    # Isolated run (SECURITY.md §4): read-only container, only ./data writable.
    mkdir -p data
    export ARIA_UID="$(id -u)" ARIA_GID="$(id -g)"
    docker compose build -q && exec docker compose run --rm aria "$@"
}

cmd_docker_test() {
    mkdir -p data
    export ARIA_UID="$(id -u)" ARIA_GID="$(id -g)"
    docker compose build -q && exec docker compose run --rm -T --entrypoint python aria tests/test_gate.py
}

cmd_lock_skills() {
    # Run only after reviewing changes to skills/*.md — this re-trusts their content.
    "$PYTHON" - <<'PY'
import hashlib, json, pathlib
skills = sorted(pathlib.Path("skills").glob("*.md"))
lock = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in skills}
pathlib.Path("skills.lock").write_text(json.dumps(lock, indent=2) + "\n")
for name, digest in lock.items():
    print(f"  {digest[:16]}…  {name}")
PY
    ok "skills.lock updated — commit it together with the skill changes."
}

cmd_test() {
    local rc=0
    for t in tests/test_*.py; do
        echo ""; echo "=== $t ==="
        "$PYTHON" "$t" 2>/dev/null || rc=1
    done
    exit $rc
}

# ── Entrypoint ────────────────────────────────────────────────────────────────
case "${1:-}" in
    install)          cmd_install ;;
    test)             cmd_test ;;
    lock-skills)      cmd_lock_skills ;;
    docker)           shift; cmd_docker "$@" ;;
    docker-test)      cmd_docker_test ;;
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
        echo "  ./run.sh test                  Run the security tests (tests/)"
        echo "  ./run.sh lock-skills           Re-hash skills/*.md after reviewing changes"
        echo "  ./run.sh docker [--auto]       Run ARIA in the locked-down container"
        echo "  ./run.sh docker-test           Run the security tests inside the container"
        echo ""
        ;;
    *)                cmd_agent "$@" ;;
esac
