# src/pyrtk/cmds/docker_cmd.py
from __future__ import annotations

import sys
import time

from ..core.utils import execute_command, strip_ansi
from ..core.filter import dedup
from ..tracker import track


def run(args: list[str], verbose: bool = False) -> None:
    sub = args[0] if args else ""
    if sub == "ps":
        cmd = ["docker", "ps", "--format", "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"]
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
    lines = raw.splitlines()
    if len(lines) <= 1:
        return "no containers running"
    result = ["CONTAINER ID | IMAGE | STATUS | NAMES"]
    for line in lines[1:]:
        parts = line.strip().split('\t')
        if len(parts) >= 4:
            result.append(f"{parts[0]} | {parts[1]} | {parts[2]} | {parts[3]}")
    return "\n".join(result)
