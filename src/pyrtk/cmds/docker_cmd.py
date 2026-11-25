# src/pyrtk/cmds/docker_cmd.py
from __future__ import annotations


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy docker ps/logs with dedup and compact table."""
    from ..core.dispatcher import run_cli_command

    run_cli_command("docker", args, verbose=verbose)


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
