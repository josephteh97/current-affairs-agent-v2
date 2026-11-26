"""
audit_report.py — summarise logs/audit.jsonl (SECURITY.md §6).

Usage:
    python audit_report.py                 # whole log (incl. rotated audit.jsonl.1)
    python audit_report.py --session ID    # one session
    python audit_report.py --last 50       # only the most recent N events

Exit code 1 if anything needs attention (denied calls, blocked fetches,
human-approved writes), so it can be used in a script or cron job.
"""

import argparse
import json
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

from tools import AUDIT_LOG


def load(path):
    events = []
    for p in (path.with_name(path.name + ".1"), path):   # oldest first
        if not p.exists():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"tool": "?", "decision": "corrupt", "reason": f"{p.name}:{n} unparseable"})
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(AUDIT_LOG))
    ap.add_argument("--session")
    ap.add_argument("--last", type=int)
    a = ap.parse_args()

    events = load(Path(a.file))
    if a.session:
        events = [e for e in events if e.get("session") == a.session]
    if a.last:
        events = events[-a.last:]
    if not events:
        print(f"No audit events in {a.file}")
        return 0

    print(f"{len(events)} events, {len({e.get('session') for e in events})} session(s), "
          f"{events[0].get('ts', '?')} → {events[-1].get('ts', '?')}\n")

    print("Decisions:", dict(Counter(e["decision"] for e in events)))
    print("Tools:    ", dict(Counter(e["tool"] for e in events)), "\n")

    hosts = Counter(urllib.parse.urlsplit(e["args"].get("url", "")).hostname
                    for e in events if e["tool"] == "web_fetch" and e["decision"] != "denied")
    if hosts:
        print("Hosts requested by web_fetch:", dict(hosts.most_common(10)), "\n")

    def show(title, rows, fmt):
        if rows:
            print(f"⚠ {title} ({len(rows)})")
            for e in rows:
                print("   ", e.get("ts", "?"), fmt(e))
            print()

    show("Denied by policy", [e for e in events if e["decision"] == "denied"],
         lambda e: f"{e['tool']}: {e.get('reason', '')[:110]}")
    show("Blocked by network policy", [e for e in events if "blocked" in e],
         lambda e: f"{e['args'].get('url', '')[:70]} — {e['blocked'][28:100]}")
    show("Human-approved (writes / unlisted URLs)", [e for e in events if e["decision"] == "user_approved"],
         lambda e: f"{e['tool']} {json.dumps(e['args'], ensure_ascii=False)[:100]}")
    show("Tool errors / corrupt lines", [e for e in events if e["decision"] in ("error", "corrupt")],
         lambda e: f"{e['tool']}: {e.get('reason', '')[:110]}")

    attention = any(e["decision"] in ("denied", "user_approved", "corrupt") or "blocked" in e
                    for e in events)
    print("Needs review." if attention else "Nothing unusual.")
    return 1 if attention else 0


if __name__ == "__main__":
    sys.exit(main())
