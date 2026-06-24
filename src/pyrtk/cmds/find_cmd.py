# src/pyrtk/cmds/find_cmd.py
from __future__ import annotations

import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_DIRS = int(os.getenv("RTK_FIND_MAX_DIRS", "20"))
_RAW_THRESHOLD = int(os.getenv("RTK_FIND_RAW_THRESHOLD", "5"))


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy find — collapse flat path list into a directory summary with counts."""
    cmd = ["find"] + args

    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_find(raw)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] find → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_find(raw: str) -> str:
    """Collapse flat find output into directory tree with file counts."""
    paths = [line.strip() for line in raw.splitlines() if line.strip()]

    if not paths:
        return "no results"

    # Small result — return as-is
    if len(paths) <= _RAW_THRESHOLD:
        return "\n".join(paths)

    # Group by parent directory
    by_dir: dict[str, int] = defaultdict(int)
    for p in paths:
        parent = str(Path(p).parent)
        by_dir[parent] += 1

    total = len(paths)
    result = [f"{total} result(s) across {len(by_dir)} director(ies)"]

    for directory, count in sorted(by_dir.items(), key=lambda x: -x[1])[:_MAX_DIRS]:
        result.append(f"  {directory}: {count} file(s)")

    if len(by_dir) > _MAX_DIRS:
        result.append(f"  ... +{len(by_dir) - _MAX_DIRS} more directories")

    return "\n".join(result)
