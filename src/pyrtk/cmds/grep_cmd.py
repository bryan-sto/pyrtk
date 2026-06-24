# src/pyrtk/cmds/grep_cmd.py
from __future__ import annotations

import os
import re
import sys
import shutil
import time
from collections import defaultdict

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_FILES = int(os.getenv("RTK_GREP_MAX_FILES", "15"))
_PREVIEW_LEN = int(os.getenv("RTK_GREP_PREVIEW_LEN", "80"))

# grep -n / rg format: filename:lineno:content
_GREP_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$")


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy grep/rg — group matches by file with counts and one preview per file.

    Auto-selects rg over grep when available.
    Exit code 1 (no matches) is not treated as an error.
    """
    tool = "rg" if shutil.which("rg") else "grep"
    cmd = [tool] + args

    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_grep(raw)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] {tool} → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    # Exit 1 from grep/rg means "no matches" — not a failure worth propagating
    if code not in (0, 1):
        raise SystemExit(code)


def _filter_grep(raw: str) -> str:
    """Group grep output by file. Shows match count + first preview per file."""
    if not raw.strip():
        return "no matches"

    by_file: dict[str, list[str]] = defaultdict(list)
    unmatched: list[str] = []

    for line in raw.splitlines():
        m = _GREP_LINE_RE.match(line)
        if m:
            filename, _, content = m.groups()
            by_file[filename].append(content.strip()[:_PREVIEW_LEN])
        else:
            unmatched.append(line)

    # Single-file mode (no filename prefix)
    if not by_file and unmatched:
        total = len(unmatched)
        result = [f"{total} match(es)"]
        for line in unmatched[:5]:
            result.append(f"  {line}")
        if total > 5:
            result.append(f"  ... +{total - 5} more")
        return "\n".join(result)

    total_matches = sum(len(v) for v in by_file.values())
    result = [f"{total_matches} match(es) in {len(by_file)} file(s)"]

    for filename, matches in sorted(by_file.items(), key=lambda x: -len(x[1]))[:_MAX_FILES]:
        preview = matches[0] if matches else ""
        result.append(f"  {filename}: {len(matches)} — {preview}")

    if len(by_file) > _MAX_FILES:
        result.append(f"  ... +{len(by_file) - _MAX_FILES} more file(s)")

    return "\n".join(result)
