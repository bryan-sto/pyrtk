# src/pyrtk/cmds/grep_cmd.py
from ..core.utils import execute_command, strip_ansi
from ..tracker import track
import time
import re


def run(args: list[str], verbose: bool = False):
    # NOTE: prefer rg (ripgrep) if available — same filter applies to both.
    cmd = ["grep"] + args
    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_grep(raw)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code not in (0, 1):
        # exit code 1 from grep means "no matches" — not an error
        exit(code)


def _filter_grep(raw: str) -> str:
    """Group grep/rg matches by file; truncate long match lines."""
    lines = raw.splitlines()
    by_file: dict[str, list[str]] = {}

    for line in lines:
        # rg/grep with line numbers: filename:lineno:match
        m = re.match(r'^([^:]+):(\d+):(.*)', line)
        if m:
            fpath, lineno, match = m.group(1), m.group(2), m.group(3)
            by_file.setdefault(fpath, []).append(f"  L{lineno}: {match[:120]}")
        elif line.strip():
            by_file.setdefault("(output)", []).append(f"  {line[:120]}")

    if not by_file:
        return "no matches"

    out: list[str] = []
    for fpath, matches in by_file.items():
        out.append(f"{fpath} ({len(matches)} match(es))")
        out.extend(matches[:5])
        if len(matches) > 5:
            out.append(f"  ... {len(matches) - 5} more")

    return "\n".join(out)
