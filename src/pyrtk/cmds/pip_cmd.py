# src/pyrtk/cmds/pip_cmd.py
from __future__ import annotations

import json

# Fields to keep from `pip show` output
_SHOW_KEEP = {"Name", "Version", "Summary", "Requires", "Required-by", "Location"}


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy pip/uv pip - compact JSON list, trimmed show output.

    Prefers uv when available. Handles list and show subcommands.
    """
    from ..core.dispatcher import run_cli_command

    effective_args = args if args else ["list"]
    run_cli_command("pip", effective_args, verbose=verbose)


def _filter_list(raw: str) -> str:
    """Parse JSON package list into compact two-column table."""
    try:
        packages: list[dict] = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:400]

    if not packages:
        return "no packages installed"

    lines = [f"{len(packages)} package(s) installed\n"]
    for pkg in sorted(packages, key=lambda x: x.get("name", "").lower()):
        name = pkg.get("name", "?")
        version = pkg.get("version", "?")
        lines.append(f"  {name:<30} {version}")

    return "\n".join(lines)


def _filter_show(raw: str) -> str:
    """Keep only the most relevant fields from pip show output."""
    result = []
    for line in raw.splitlines():
        if ":" in line:
            key = line.split(":", 1)[0].strip()
            if key in _SHOW_KEEP:
                result.append(line)
    return "\n".join(result) if result else raw[:300]
