# src/pyrtk/cmds/cargo_cmd.py
from __future__ import annotations

import sys
import time

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_LINES = 60


def run(args: list[str], verbose: bool = False, cwd: str = ".") -> None:
    """Proxy cargo - compact test, clippy, and build output."""
    sub = args[0] if args else "build"
    cmd = ["cargo"] + args

    t0 = time.time()
    stdout, stderr, code = execute_command(cmd, cwd=cwd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)

    if sub == "test":
        filtered = _filter_cargo_test(raw, code)
    elif sub == "clippy":
        filtered = _filter_cargo_clippy(raw)
    else:
        filtered = _filter_cargo_build(raw, code)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] cargo {sub} → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms, cwd=cwd)

    if code != 0:
        raise SystemExit(code)


def _filter_cargo_test(raw: str, code: int) -> str:
    """Filter cargo test output - hide passing tests, keep failures and summary."""
    lines = raw.splitlines()
    failures: list[str] = []
    in_failures = False
    summary_line = ""

    for line in lines:
        if line.startswith("failures:") or "---- " in line:
            in_failures = True
        if "test result:" in line:
            summary_line = line
            in_failures = False
        if in_failures:
            failures.append(line)

    if not failures:
        if code == 0:
            return summary_line or "all tests passed ✓"
        return summary_line or (raw[:400] if raw.strip() else "cargo test failed")

    result = failures[:_MAX_LINES]
    if summary_line and summary_line not in result:
        result.append(summary_line)
    return "\n".join(result)


def _filter_cargo_clippy(raw: str) -> str:
    """Filter cargo clippy/check output - keep warnings and error summaries."""
    lines = raw.splitlines()
    diagnostics = [
        line_item for line_item in lines
        if line_item.startswith("warning:") or line_item.startswith("error:")
    ]
    if not diagnostics:
        return "clippy: clean ✓" if "Finished" in raw else raw[:300]

    return f"clippy: {len(diagnostics)} diagnostic(s)\n" + "\n".join(f"  {d}" for d in diagnostics[:20])


def _filter_cargo_build(raw: str, code: int) -> str:
    """Filter cargo build output - errors/warnings only."""
    lines = raw.splitlines()
    errs = [
        line_item for line_item in lines
        if "error" in line_item.lower() or "warning" in line_item.lower()
    ]
    if not errs:
        if code == 0:
            return "build ok ✓"
        return raw[:400] if raw.strip() else f"build failed (exit {code})"
    return "\n".join(errs[:_MAX_LINES])
