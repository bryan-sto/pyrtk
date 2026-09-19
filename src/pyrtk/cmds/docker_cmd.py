# src/pyrtk/cmds/docker_cmd.py
from __future__ import annotations

import sys
import time

from ..core.filter import dedup
from ..core.utils import execute_command, strip_ansi
from ..tracker import track


def run(args: list[str], verbose: bool = False) -> None:
    sub = args[0] if args else ""
    if sub == "ps":
        cmd = ["docker", "ps", "--format", "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"] + args[1:]
    else:
        cmd = ["docker"] + args

    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)

    if sub == "ps":
        filtered = _filter_ps(raw)
    elif sub == "logs":
        filtered = dedup(raw)
    else:
        filtered = raw

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] docker {sub} → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_ps(raw: str) -> str:
    import re
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) <= 1:
        return "no containers running"
    result = ["CONTAINER ID | IMAGE | STATUS | NAMES"]
    for line in lines[1:]:
        line_clean = line.strip()
        if not line_clean:
            continue
        if "\t" in line_clean:
            parts = [p.strip() for p in line_clean.split("\t") if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r"\s{2,}", line_clean) if p.strip()]
        if len(parts) >= 6:
            # 7-column standard format: ID (0), IMAGE (1), STATUS (-3), NAMES (-1)
            result.append(f"{parts[0]} | {parts[1]} | {parts[-3]} | {parts[-1]}")
        elif len(parts) >= 4:
            # 4-column custom table format: ID, IMAGE, STATUS, NAMES
            result.append(f"{parts[0]} | {parts[1]} | {parts[2]} | {parts[3]}")
        elif len(parts) >= 2:
            result.append(" | ".join(parts))
        else:
            result.append(line_clean)
    return "\n".join(result)
