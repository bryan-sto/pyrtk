# src/pyrtk/cmds/docker_cmd.py
from ..core.utils import execute_command, strip_ansi
from ..core.filter import dedup
import re

def run(args: list[str], verbose: bool = False):
    cmd = ["docker"] + args
    stdout, stderr, code = execute_command(cmd)
    raw = strip_ansi(stdout + stderr)
    sub = args[0] if args else ""
    if sub == "ps":
        filtered = _filter_ps(raw)
    elif sub == "logs":
        filtered = dedup(raw)
    else:
        filtered = raw
    print(filtered)

def _filter_ps(raw: str) -> str:
    lines = raw.splitlines()
    if len(lines) <= 1:
        return "no containers running"
    result = ["CONTAINER ID | IMAGE | STATUS | NAMES"]
    for line in lines[1:]:
        parts = re.split(r'\s{2,}', line.strip())
        if len(parts) >= 6:
            result.append(f"{parts[0]} | {parts[1]} | {parts[4]} | {parts[-1]}")
    return "\n".join(result)
