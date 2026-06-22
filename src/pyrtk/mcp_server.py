# src/pyrtk/mcp_server.py
from mcp.server.fastmcp import FastMCP
import requests
import datetime
import time
import os
import re
import shlex
from pathlib import Path
from .core.utils import execute_command, estimate_tokens, strip_ansi

mcp = FastMCP("pyrtk")


@mcp.tool()
def rtk_run_command(command: str, cwd: str = ".") -> str:
    """Run shell command with auto token compression and MemCore logging."""
    t0 = time.time()

    args = shlex.split(command)
    if not args:
        return ""

    main_cmd = args[0]
    cmd_args = args[1:]

    stdout, stderr, code = execute_command(args, cwd=cwd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)

    # ── git ──────────────────────────────────────────────────────────────────
    if main_cmd == "git":
        from .cmds.git import _filter_status, _filter_log, _filter_diff, _filter_simple
        sub = cmd_args[0] if cmd_args else ""
        if sub == "status":
            std_p, _, _ = execute_command(["git", "status", "--porcelain"], cwd=cwd)
            filtered = _filter_status(std_p)
        elif sub == "log":
            filtered = _filter_log(raw)
        elif sub in ("add", "commit", "push", "pull"):
            filtered = _filter_simple(raw, sub)
        elif sub == "diff":
            filtered = _filter_diff(raw, cmd_args)
        else:
            filtered = raw

    # ── pytest ────────────────────────────────────────────────────────────────
    elif main_cmd == "pytest":
        from .cmds.pytest_cmd import _filter_pytest
        filtered = _filter_pytest(raw)

    # ── docker ───────────────────────────────────────────────────────────────
    elif main_cmd == "docker":
        from .cmds.docker_cmd import _filter_ps, dedup
        sub = cmd_args[0] if cmd_args else ""
        if sub == "ps":
            filtered = _filter_ps(raw)
        elif sub == "logs":
            filtered = dedup(raw)
        else:
            filtered = raw

    # ── ls ────────────────────────────────────────────────────────────────────
    elif main_cmd == "ls":
        target = Path(cmd_args[0]) if cmd_args else Path(".")
        if not target.exists():
            return f"Path not found: {target}"
        if target.is_file():
            return f"{target.name} ({target.stat().st_size}B)"
        dirs = []
        files_count = 0
        for item in target.iterdir():
            if item.name.startswith('.'):
                continue
            if item.is_dir():
                subfiles = sum(1 for _ in item.glob('*') if _.is_file())
                dirs.append(f"{item.name}/ ({subfiles} files)")
            else:
                files_count += 1
        output = []
        if dirs:
            output.extend(dirs)
        if files_count:
            output.append(f"files: {files_count} file(s) in root")
        filtered = "\n".join(output) if output else "empty directory"

    # ── ruff ──────────────────────────────────────────────────────────────────
    elif main_cmd == "ruff":
        filtered = _filter_ruff(raw)

    # ── grep / rg ─────────────────────────────────────────────────────────────
    elif main_cmd in ("grep", "rg"):
        filtered = _filter_grep(raw)

    # ── pip ───────────────────────────────────────────────────────────────────
    elif main_cmd == "pip":
        sub = cmd_args[0] if cmd_args else ""
        if sub == "list":
            filtered = _filter_pip_list(raw)
        else:
            filtered = raw

    # ── find ──────────────────────────────────────────────────────────────────
    elif main_cmd == "find":
        filtered = _filter_find(raw)

    else:
        filtered = raw

    # ── MemCore logging ───────────────────────────────────────────────────────
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = (saved / inp * 100) if inp > 0 else 0.0

    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "project": Path(cwd).resolve().name,
        "command": command,
        "input_t": inp,
        "output_t": out,
        "saved_t": saved,
        "pct": pct,
        "exec_ms": exec_ms,
    }
    port = os.getenv("MEMCORE_PORT", "3111")
    try:
        requests.post(
            f"http://localhost:{port}/agentmemory/command/log",
            json=payload,
            timeout=2,
        )
    except requests.exceptions.RequestException:
        pass

    return filtered


# ── Filter helpers ────────────────────────────────────────────────────────────

def _filter_ruff(raw: str) -> str:
    """Group ruff check output by file; surface error counts per file."""
    lines = raw.splitlines()
    # ruff outputs: path/to/file.py:line:col: CODE message
    by_file: dict[str, list[str]] = {}
    summary_lines: list[str] = []
    for line in lines:
        m = re.match(r'^(.+?\.py):(\d+:\d+:.*)', line)
        if m:
            fpath = m.group(1)
            detail = m.group(2)
            by_file.setdefault(fpath, []).append(detail)
        elif line.strip():
            summary_lines.append(line)

    if not by_file and not summary_lines:
        return "ruff: no issues found"

    out: list[str] = []
    for fpath, errors in by_file.items():
        out.append(f"{fpath} ({len(errors)} issue(s))")
        # Show at most 3 errors per file to keep output compact
        for e in errors[:3]:
            out.append(f"  {e}")
        if len(errors) > 3:
            out.append(f"  ... {len(errors) - 3} more")

    if summary_lines:
        out.append("")
        out.extend(summary_lines[-3:])  # last 3 summary lines (totals)

    return "\n".join(out)


def _filter_grep(raw: str) -> str:
    """Group grep/rg matches by file; truncate long match lines."""
    lines = raw.splitlines()
    by_file: dict[str, list[str]] = {}
    for line in lines:
        # rg/grep: filename:line_number:match  or  filename:match
        m = re.match(r'^([^:]+):(\d+):(.*)', line)
        if m:
            fpath, lineno, match = m.group(1), m.group(2), m.group(3)
            by_file.setdefault(fpath, []).append(f"  L{lineno}: {match[:120]}")
        elif line.strip():
            by_file.setdefault("(output)", []).append(f"  {line[:120]}")

    if not by_file:
        return "no matches"

    out: list[str] = []
    for fpath, matches in by_file.items():
        out.append(f"{fpath} ({len(matches)} match(es))")
        # Cap at 5 matches per file
        out.extend(matches[:5])
        if len(matches) > 5:
            out.append(f"  ... {len(matches) - 5} more")
    return "\n".join(out)


def _filter_pip_list(raw: str) -> str:
    """Compact pip list — one package per line, aligned columns."""
    lines = raw.splitlines()
    # Skip header rows ("Package", "---")
    pkgs = [l for l in lines if l.strip() and not l.startswith("-") and not l.lower().startswith("package")]
    if not pkgs:
        return raw[:300]
    # Normalise spacing: name version
    compact = []
    for pkg in pkgs:
        parts = pkg.split()
        if len(parts) >= 2:
            compact.append(f"{parts[0]:<30} {parts[1]}")
        else:
            compact.append(pkg)
    return f"{len(compact)} packages\n" + "\n".join(compact)


def _filter_find(raw: str) -> str:
    """Collapse find output to directory-level summary."""
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return "no results"

    # Group by parent directory
    by_dir: dict[str, int] = {}
    for line in lines:
        parent = str(Path(line).parent)
        by_dir[parent] = by_dir.get(parent, 0) + 1

    out: list[str] = []
    for d, count in sorted(by_dir.items()):
        out.append(f"{d}/ ({count} result(s))")

    total = len(lines)
    out.append(f"\ntotal: {total} result(s) across {len(by_dir)} director{'y' if len(by_dir) == 1 else 'ies'}")
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run()
