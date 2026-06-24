# src/pyrtk/cmds/err_cmd.py
from __future__ import annotations

import re
import sys
import time

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_OUTPUT_LINES = 60

_ERROR_RE = re.compile(
    r"(error|exception|traceback|fatal|critical|failed|failure|"
    r"panic|abort|denied|rejected|not found|cannot|could not|unable to)",
    re.IGNORECASE,
)


def run(args: list[str], verbose: bool = False) -> None:
    """Generic wrapper — return only stderr and error-pattern lines from stdout.

    Usage: pyrtk err <any command> [args...]

    Use this for commands not yet covered by dedicated modules. It will
    always surface errors even if they're buried in verbose output.
    """
    if not args:
        print("Usage: pyrtk err <command> [args...]", file=sys.stderr)
        raise SystemExit(1)

    t0 = time.time()
    stdout, stderr, code = execute_command(args)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_errors(stdout, stderr)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] err → {pct}% saved (exit: {code})", file=sys.stderr)

    if filtered.strip():
        print(filtered)
    elif code != 0:
        print(f"exit {code} (no error output captured — run command directly for full output)")
    else:
        print("ok")

    track(" ".join(args), f"pyrtk err {' '.join(args)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_errors(stdout: str, stderr: str) -> str:
    """Return stderr lines first, then error-pattern stdout lines. Deduplicated."""
    result: list[str] = []

    # stderr always included
    for line in stderr.splitlines():
        if line.strip():
            result.append(line)

    # stdout — error-pattern lines only
    for line in stdout.splitlines():
        if _ERROR_RE.search(line):
            result.append(line)

    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for line in result:
        key = line.strip()
        if key not in seen:
            seen.add(key)
            deduped.append(line)

    return "\n".join(deduped[:_MAX_OUTPUT_LINES])
