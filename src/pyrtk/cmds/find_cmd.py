# src/pyrtk/cmds/find_cmd.py
from ..core.utils import execute_command, strip_ansi
from ..tracker import track
from pathlib import Path
import time


def run(args: list[str], verbose: bool = False):
    cmd = ["find"] + args
    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_find(raw)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        exit(code)


def _filter_find(raw: str) -> str:
    """Collapse find output to a directory-level summary."""
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return "no results"

    by_dir: dict[str, int] = {}
    for line in lines:
        parent = str(Path(line).parent)
        by_dir[parent] = by_dir.get(parent, 0) + 1

    out: list[str] = []
    for d, count in sorted(by_dir.items()):
        out.append(f"{d}/ ({count} result(s))")

    total = len(lines)
    dirs = len(by_dir)
    out.append(f"\ntotal: {total} result(s) across {dirs} director{'y' if dirs == 1 else 'ies'}")
    return "\n".join(out)
