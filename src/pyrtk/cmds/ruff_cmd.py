# src/pyrtk/cmds/ruff_cmd.py
from ..core.utils import execute_command, strip_ansi
from ..tracker import track
import time
import re


def run(args: list[str], verbose: bool = False):
    cmd = ["ruff"] + args
    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_ruff(raw)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        exit(code)


def _filter_ruff(raw: str) -> str:
    """Group ruff check output by file; surface error counts per file."""
    lines = raw.splitlines()
    by_file: dict[str, list[str]] = {}
    summary_lines: list[str] = []

    for line in lines:
        # ruff format: path/to/file.py:line:col: CODE message
        m = re.match(r'^(.+?\.py):(\d+:\d+:.*)', line)
        if m:
            fpath = m.group(1)
            detail = m.group(2)
            by_file.setdefault(fpath, []).append(detail)
        elif line.strip():
            summary_lines.append(line)

    if not by_file and not summary_lines:
        return "ruff: no issues found"

    out: list[str] = []
    for fpath, errors in by_file.items():
        out.append(f"{fpath} ({len(errors)} issue(s))")
        for e in errors[:3]:
            out.append(f"  {e}")
        if len(errors) > 3:
            out.append(f"  ... {len(errors) - 3} more")

    if summary_lines:
        out.append("")
        out.extend(summary_lines[-3:])

    return "\n".join(out)
