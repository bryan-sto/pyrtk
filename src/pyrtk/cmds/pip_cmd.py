# src/pyrtk/cmds/pip_cmd.py
from __future__ import annotations

import json
import sys
import shutil
import time

from ..core.utils import execute_command
from ..tracker import track

# Fields to keep from `pip show` output
_SHOW_KEEP = {"Name", "Version", "Summary", "Requires", "Required-by", "Location"}


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy pip/uv pip — compact JSON list, trimmed show output.

    Prefers uv when available. Handles list and show subcommands.
    """
    tool = "uv" if shutil.which("uv") else "pip"
    sub = args[0] if args else "list"

    if sub == "list":
        cmd = ([tool, "pip", "list", "--format", "json"]
               if tool == "uv"
               else ["pip", "list", "--format", "json"])
        t0 = time.time()
        stdout, stderr, code = execute_command(cmd)
        exec_ms = int((time.time() - t0) * 1000)
        raw = stdout + stderr
        filtered = _filter_list(raw)

    elif sub == "show":
        cmd = ([tool, "pip", "show"] + args[1:]
               if tool == "uv"
               else ["pip", "show"] + args[1:])
        t0 = time.time()
        stdout, stderr, code = execute_command(cmd)
        exec_ms = int((time.time() - t0) * 1000)
        raw = stdout + stderr
        filtered = _filter_show(raw)

    else:
        cmd = ([tool, "pip"] + args if tool == "uv" else ["pip"] + args)
        t0 = time.time()
        stdout, stderr, code = execute_command(cmd)
        exec_ms = int((time.time() - t0) * 1000)
        raw = stdout + stderr
        filtered = raw

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] pip {sub} → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(cmd), f"pyrtk pip {sub}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


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
