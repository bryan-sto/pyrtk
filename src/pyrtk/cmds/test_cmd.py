# src/pyrtk/cmds/test_cmd.py
from __future__ import annotations

import os
import re
import sys
import time

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_FAILURE_LINES = int(os.getenv("RTK_MAX_FAILURE_LINES", "80"))

# Patterns that mark the start of a failure block across runners
_FAILURE_START_RE = re.compile(
    r"(=+\s*(FAILURES|ERRORS|FAILED TESTS|Error Summary)\s*=+|"  # pytest
    r"● .+|"                    # Jest
    r"FAIL .+\.(?:js|ts|jsx|tsx)|"  # Jest file-level
    r"^\s+\d+\) .+|"           # Mocha numbered failure
    r"Failures:\s*$|"          # RSpec
    r"--- FAIL:|"              # Go test
    r"FAILED\s+\w)",           # Generic
    re.IGNORECASE | re.MULTILINE,
)

# Summary line patterns (used to extract the final verdict)
_SUMMARY_RE = re.compile(
    r"(\d+\s+(passed|failed|pending|skipped|error|flaky)|"
    r"\d+\s+examples?,\s*\d+\s+failure|"   # RSpec
    r"Tests run:\s*\d+|"                   # JUnit
    r"^ok\s+\S+\s+[\d.]+s$|"             # Go
    r"Test Suites?:.*\n.*Tests?:)",        # Jest
    re.IGNORECASE | re.MULTILINE,
)

_COLLECTION_ERROR_RE = re.compile(
    r"(no tests? (ran|collected|found)|collected 0 items|import error|syntaxerror)",
    re.IGNORECASE,
)


def run(args: list[str], verbose: bool = False) -> None:
    """Generic test runner wrapper — show failures only.

    Usage: pyrtk test <command> [args...]
    Example: pyrtk test go test ./...
             pyrtk test npx jest --ci

    Works with: pytest, Jest, Mocha, Go test, RSpec, dotnet test, cargo test.
    Falls back to last 20 lines on unrecognised format.
    """
    if not args:
        print("Usage: pyrtk test <command> [args...]", file=sys.stderr)
        raise SystemExit(1)

    t0 = time.time()
    stdout, stderr, code = execute_command(args)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_test_output(raw, code)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] test → {pct}% saved (exit: {code})", file=sys.stderr)

    print(filtered)
    track(" ".join(args), f"pyrtk test {' '.join(args)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_test_output(raw: str, exit_code: int) -> str:
    """Extract failure block + summary from any test runner output."""
    lines = raw.splitlines()

    # Detect collection errors before anything else
    if _COLLECTION_ERROR_RE.search(raw):
        # Return the relevant section — don't say "all passed"
        relevant = [l for l in lines if l.strip() and not l.strip().startswith("=")]
        return "\n".join(relevant[:20]) or f"Collection error (exit {exit_code})"

    # Extract summary lines
    summary_matches = list(_SUMMARY_RE.finditer(raw))
    summary_line = summary_matches[-1].group(0).strip() if summary_matches else ""

    # Extract failure block
    failures: list[str] = []
    in_failure = False

    for line in lines:
        if _FAILURE_START_RE.search(line):
            in_failure = True

        if in_failure:
            failures.append(line)

        # Stop at summary (but only after we've captured some failures)
        if in_failure and len(failures) > 3 and _SUMMARY_RE.search(line):
            break

    if not failures:
        if exit_code == 0:
            return summary_line or "all tests passed"
        # Non-zero exit but no structured failures — tail of output
        tail = lines[-20:] if len(lines) > 20 else lines
        return "\n".join(tail) or f"tests failed (exit {exit_code})"

    result = failures[:_MAX_FAILURE_LINES]
    if summary_line and summary_line not in result[-1]:
        result.append(summary_line)

    if len(failures) > _MAX_FAILURE_LINES:
        result.append(f"[{len(failures) - _MAX_FAILURE_LINES} lines omitted — run directly for full output]")

    return "\n".join(result)
