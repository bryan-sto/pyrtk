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


def _python_find(args: list[str], cwd: str = ".") -> list[str]:
    """Pure Python fallback for find on systems without GNU find (e.g. native Windows)."""
    root = Path(cwd)
    pattern = "*"
    i = 0
    is_abs = False
    if args and not args[0].startswith("-"):
        target_path = Path(args[0])
        is_abs = target_path.is_absolute()
        root = target_path if is_abs else (root / target_path)
        i = 1
    while i < len(args):
        if args[i] in ("-name", "-iname") and i + 1 < len(args):
            pattern = args[i + 1].strip('"\'')
            i += 2
        else:
            i += 1

    matches: list[str] = []
    if root.exists():
        cwd_resolved = Path(cwd).resolve()
        for p in root.rglob(pattern):
            try:
                if any(part.startswith(".") for part in p.relative_to(root).parts):
                    continue
                if is_abs:
                    matches.append(str(p))
                else:
                    try:
                        matches.append(str(p.resolve().relative_to(cwd_resolved)))
                    except ValueError:
                        matches.append(str(p))
            except Exception:
                continue
    return matches


def run(args: list[str], verbose: bool = False, cwd: str = ".") -> None:
    """Proxy find - collapse flat path list into a directory summary with counts."""
    # Check if native find is Windows System32 find.exe (which does string matching, not file search)
    import shutil
    find_bin = shutil.which("find")
    is_win_system_find = sys.platform == "win32" and find_bin and "system32" in find_bin.lower()

    t0 = time.time()
    if is_win_system_find or (sys.platform == "win32" and any(a.startswith("-") for a in args)):
        paths = _python_find(args, cwd=cwd)
        raw = "\n".join(paths)
        code = 0
    else:
        cmd = ["find"] + args
        stdout, stderr, code = execute_command(cmd, cwd=cwd)
        raw = strip_ansi(stdout + stderr)

    exec_ms = int((time.time() - t0) * 1000)
    filtered = _filter_find(raw)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] find → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(["find"] + args), f"pyrtk {' '.join(['find'] + args)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_find(raw: str) -> str:
    """Collapse flat find output into directory tree with file counts."""
    if not raw.strip():
        return "no results"

    if any(w in raw.lower() for w in ("parameter format not correct", "file not found", "error:")):
        return raw[:400]

    paths = [line.strip() for line in raw.splitlines() if line.strip()]

    if not paths:
        return "no results"

    # Small result - return as-is
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
