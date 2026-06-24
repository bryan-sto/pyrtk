# src/pyrtk/cmds/ls_cmd.py
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

from ..tracker import track


def run(args: list[str], verbose: bool = False) -> None:
    cmd = ["ls"] + args
    t0 = time.time()

    target = Path(args[0]) if args else Path(".")
    if not target.exists():
        print(f"Path not found: {target}", file=sys.stderr)
        raise SystemExit(1)

    if target.is_file():
        filtered = f"{target.name} ({target.stat().st_size}B)"
        print(filtered)
        exec_ms = int((time.time() - t0) * 1000)
        track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", filtered, filtered, exec_ms)
        return

    dirs = []
    files_count = 0
    try:
        items = sorted(target.iterdir())
    except PermissionError:
        print(f"Permission denied: {target}", file=sys.stderr)
        raise SystemExit(1)

    for item in items:
        if item.name.startswith('.'):
            continue
        if item.is_dir():
            try:
                # Limit checking to 51 children to avoid huge directories causing CPU lag.
                children = list(itertools.islice(
                    (f for f in item.iterdir() if f.is_file()), 51
                ))
                label = f"{len(children)} files" if len(children) < 51 else "50+ files"
            except PermissionError:
                label = "no access"
            dirs.append(f"{item.name}/ ({label})")
        elif item.is_file():
            files_count += 1

    output = []
    if dirs:
        output.extend(dirs)
    if files_count:
        output.append(f"files: {files_count} file(s) in root")
    filtered = "\n".join(output) if output else "empty directory"

    if verbose:
        # Since it's a python tool, raw is same as filtered
        print(f"[pyrtk] ls → 0% saved", file=sys.stderr)

    print(filtered)
    exec_ms = int((time.time() - t0) * 1000)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", filtered, filtered, exec_ms)
