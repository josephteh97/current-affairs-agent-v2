"""Tiny shared helper for the security tests (no test framework needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

failures = 0


def section(title: str) -> None:
    print(f"── {title}")


def check(desc: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += not ok
    print(("PASS " if ok else "FAIL ") + f"{desc:58} {detail.splitlines()[0][:80] if detail else ''}")


def finish() -> None:
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
