# src/pyrtk/cmds/pytest_cmd.py
from __future__ import annotations

import os
import re
import sys
import time

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_FAILURE_LINES = int(os.getenv("RTK_MAX_FAILURE_LINES", "50"))


def run(args: list[str], verbose: bool = False) -> None:
    cmd = ["pytest"] + args
    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_pytest(raw)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] pytest → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_pytest(raw: str) -> str:
    lines = raw.splitlines()
    failures = []
    in_failures_section = False

    for line in lines:
        if "=== FAILURES ===" in line:
            in_failures_section = True
            failures.append(line)
            continue
        if "=== ERRORS ===" in line:
            # NOTE: Reset rather than continue accumulating — ERRORS is a
            # distinct section from FAILURES; without this, if ERRORS appears
            # after FAILURES, lines bleed together.
            in_failures_section = True
            failures.append("")  # blank separator
            failures.append(line)
            continue
        if re.match(r'===+ .* in \d+\.\d+s ===+', line):
            # Summary line
            failures.append(line)
            break
        if in_failures_section:
            failures.append(line)

    if not failures:
        # Check for compact failure lines (e.g. from --tb=short, --tb=line, or -q)
        compact_failures = [
            line_item for line_item in lines
            if (
                line_item.startswith("FAILED ")
                or "AssertionError" in line_item
                or ("error" in line_item.lower() and not line_item.startswith("=="))
            )
        ]
        if compact_failures:
            summary = [line_item for line_item in lines if re.search(r'\d+ (passed|failed|error|warning)', line_item)]
            res = compact_failures[:20]
            if summary and summary[-1] not in res:
                res.append(summary[-1])
            return "\n".join(res)

        # Check if there is a summary line at least
        summary = [line_item for line_item in lines if re.search(r'\d+ (passed|failed|error|warning)', line_item)]
        if summary:
            return summary[-1]
        if "no tests ran" in raw.lower() or "collected 0 items" in raw.lower():
            return "no tests collected"
        if "error" in raw.lower():
            return raw[:400]  # collection error — return raw so agent sees it
        return "all tests passed"

    # Return at most the configured lines of failures to avoid token bloat
    return "\n".join(failures[:_MAX_FAILURE_LINES])
