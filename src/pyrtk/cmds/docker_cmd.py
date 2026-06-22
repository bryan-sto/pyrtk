# src/pyrtk/cmds/docker_cmd.py
from ..core.utils import execute_command, strip_ansi
from ..core.filter import dedup
from ..tracker import track
import time
import re

# NOTE: Precompiled once — _PS_SEP is used per-row in _filter_ps(), so
# compiling inside the loop would add overhead proportional to container count.
_PS_SEP = re.compile(r'\s{2,}')


def run(args: list[str], verbose: bool = False):
    cmd = ["docker"] + args
    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    sub = args[0] if args else ""

    if sub == "ps":
        filtered = _filter_ps(raw)
    elif sub == "logs":
        filtered = dedup(raw)
    else:
        filtered = raw

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        exit(code)


def _filter_ps(raw: str) -> str:
    lines = raw.splitlines()
    if len(lines) <= 1:
        return "no containers running"
    result = ["CONTAINER ID | IMAGE | STATUS | NAMES"]
    for line in lines[1:]:
        parts = _PS_SEP.split(line.strip())
        if len(parts) >= 6:
            result.append(f"{parts[0]} | {parts[1]} | {parts[4]} | {parts[-1]}")
    return "\n".join(result)
