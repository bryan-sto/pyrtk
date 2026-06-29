# src/pyrtk/mcp_server.py
from __future__ import annotations

import datetime
import itertools
import logging
import os
import re
import shlex
import threading
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

from .core.filter import FilterLevel, code_filter, dedup
from .core.utils import execute_command, estimate_tokens, strip_ansi
from .cmds.git import _filter_status, _filter_log, _filter_diff, _filter_simple
from .cmds.pytest_cmd import _filter_pytest
from .cmds.docker_cmd import _filter_ps
from .cmds.ruff_cmd import _filter_check_json, _filter_check_text, _filter_format as _ruff_format
from .cmds.grep_cmd import _filter_grep
from .cmds.find_cmd import _filter_find
from .cmds.pip_cmd import _filter_list as _pip_list, _filter_show as _pip_show
from .cmds.err_cmd import _filter_errors
from .cmds.test_cmd import _filter_test_output

# Custom logging matching memcore.log style
def write_log(tag: str, msg: str) -> None:
    """Write log messages to pyrtk.log in project root matching MemCore format."""
    try:
        now_str = datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        log_path = Path(__file__).parent.parent.parent / "pyrtk.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now_str}] [{tag}] {msg}\n")
    except Exception:
        pass

mcp = FastMCP("pyrtk")

_MEMCORE_PORT = os.getenv("MEMCORE_PORT", "3111")
_SECRET_RE = re.compile(
    r"(bearer|authorization|token|password|secret|key|auth)(?:\s+|=)\S+",
    re.IGNORECASE,
)


def _scrub(cmd: str) -> str:
    """Remove credential-like strings before logging to MemCore."""
    return _SECRET_RE.sub(r"\1 [REDACTED]", cmd)


def _post_to_memcore(payload: dict) -> None:
    """Fire-and-forget MemCore log call. Runs in daemon thread."""
    try:
        requests.post(
            f"http://localhost:{_MEMCORE_PORT}/agentmemory/command/log",
            json=payload,
            timeout=2,
        )
    except requests.exceptions.RequestException:
        pass


def _log(command: str, cwd: str, raw: str, filtered: str, exec_ms: int) -> None:
    """Build and fire the MemCore tracking payload asynchronously."""
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = round((saved / inp * 100) if inp > 0 else 0.0, 1)

    payload = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
        "project": Path(cwd).resolve().name,
        "command": _scrub(command),
        "input_t": inp,
        "output_t": out,
        "saved_t": saved,
        "pct": pct,
        "exec_ms": exec_ms,
    }
    # Log locally in pyrtk.log
    write_log("CMD", f"rtk_run_command - Cmd: \"{_scrub(command)}\", Saved: {saved} tokens ({pct}%), Exec: {exec_ms}ms")
    threading.Thread(target=_post_to_memcore, args=(payload,), daemon=True).start()


def _validate_cwd(cwd: str) -> str | None:
    """Return error string if cwd is invalid, else None."""
    resolved = Path(cwd).resolve()
    if not resolved.exists():
        return f"Error: cwd does not exist: {cwd}"
    if not resolved.is_dir():
        return f"Error: cwd is not a directory: {cwd}"
    return None


@mcp.tool()
def rtk_run_command(command: str, cwd: str = ".") -> str:
    """Run a shell command with automatic token compression and MemCore logging.

    Supports: git, pytest, ruff, grep/rg, find, pip/uv, docker, ls,
              read (source file), err (generic errors-only), test (generic failures-only).
    Falls back to raw output for any unrecognised command.

    Args:
        command: Full shell command string. Quoted arguments are supported.
        cwd:     Working directory for the command. Defaults to current directory.

    Returns:
        Compressed command output as a string.
    """
    err = _validate_cwd(cwd)
    if err:
        return err

    try:
        import platform
        is_windows = platform.system() == "Windows"
        args = [a.strip('"\'') for a in shlex.split(command, posix=not is_windows)]
    except ValueError as e:
        return f"Error: could not parse command: {e}"

    if not args:
        return ""

    main_cmd = args[0]
    cmd_args = args[1:]

    t0 = time.time()
    # Check git status or diff to intercept and run optimised calls
    if main_cmd == "git" and cmd_args:
        sub = cmd_args[0]
        if sub == "status":
            stdout, stderr, code = execute_command(["git", "status", "--porcelain"], cwd=cwd)
        elif sub == "diff":
            # Always use --stat for diff under rtk_run_command unless stat option already present
            diff_args = ["git", "diff"]
            has_stat_option = any(arg in cmd_args for arg in ("--stat", "--name-only", "--name-status", "-p", "--patch"))
            if not has_stat_option:
                diff_args.append("--stat")
            diff_args.extend(cmd_args[1:])
            stdout, stderr, code = execute_command(diff_args, cwd=cwd)
        else:
            stdout, stderr, code = execute_command(args, cwd=cwd)
    else:
        stdout, stderr, code = execute_command(args, cwd=cwd)

    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = raw  # default — overwritten below

    try:
        if main_cmd == "git":
            sub = cmd_args[0] if cmd_args else ""
            if sub == "status":
                filtered = _filter_status(raw)
                # Estimate baseline for status token calculation
                num_lines = len(raw.splitlines())
                baseline_len = 500 + num_lines * 80
                raw = " " * baseline_len  # set raw to baseline length for estimate_tokens
            elif sub == "log":
                filtered = _filter_log(raw)
            elif sub in ("add", "commit", "push", "pull"):
                filtered = _filter_simple(raw, sub)
            elif sub == "diff":
                filtered = _filter_diff(raw, cmd_args)
                if len(cmd_args) == 1:
                    # Estimate baseline for diff token calculation
                    raw = " " * (len(raw) * 5)
            else:
                filtered = raw

        elif main_cmd == "pytest":
            filtered = _filter_pytest(raw)

        elif main_cmd == "ruff":
            sub = cmd_args[0] if cmd_args else "check"
            if sub == "check":
                filtered = _filter_check_json(cmd_args) or _filter_check_text(raw)
            elif sub == "format":
                filtered = _ruff_format(raw)
            else:
                filtered = raw

        elif main_cmd in ("grep", "rg"):
            filtered = _filter_grep(raw)

        elif main_cmd == "find":
            filtered = _filter_find(raw)

        elif main_cmd in ("pip", "uv"):
            sub = cmd_args[0] if cmd_args else ""
            effective_sub = cmd_args[1] if main_cmd == "uv" and sub == "pip" and len(cmd_args) > 1 else sub
            if effective_sub == "list":
                tool = main_cmd
                json_cmd = (
                    [tool, "pip", "list", "--format", "json"]
                    if tool == "uv"
                    else ["pip", "list", "--format", "json"]
                )
                json_out, _, _ = execute_command(json_cmd, cwd=cwd)
                filtered = _pip_list(json_out)
            elif effective_sub == "show":
                filtered = _pip_show(raw)
            else:
                filtered = raw

        elif main_cmd == "docker":
            sub = cmd_args[0] if cmd_args else ""
            if sub == "ps":
                filtered = _filter_ps(raw)
            elif sub == "logs":
                filtered = dedup(raw)
            else:
                filtered = raw

        elif main_cmd == "ls":
            target = Path(cmd_args[0]) if cmd_args else Path(cwd)
            if not target.is_absolute():
                target = Path(cwd) / target
            if target.exists() and target.is_dir():
                dirs, files_count = [], 0
                for item in sorted(target.iterdir()):
                    if item.name.startswith("."):
                        continue
                    if item.is_dir():
                        try:
                            children = list(itertools.islice(
                                (f for f in item.iterdir() if f.is_file()), 51
                            ))
                            label = f"{len(children)} files" if len(children) < 51 else "50+ files"
                        except PermissionError:
                            label = "no access"
                        dirs.append(f"{item.name}/ ({label})")
                    elif item.is_file():
                        files_count += 1
                parts = dirs
                if files_count:
                    parts.append(f"files: {files_count} file(s) in root")
                filtered = "\n".join(parts) if parts else "empty directory"
            else:
                filtered = raw

        elif main_cmd == "read":
            if cmd_args:
                filepath = Path(cwd) / cmd_args[0] if not Path(cmd_args[0]).is_absolute() else Path(cmd_args[0])
                level_str = "minimal"
                for a in cmd_args[1:]:
                    if a in ("none", "minimal", "aggressive"):
                        level_str = a
                try:
                    level = FilterLevel(level_str)
                    file_raw = filepath.read_text(encoding="utf-8", errors="replace")
                    lang_ext = filepath.suffix.lower()
                    from src.pyrtk.cmds.read_cmd import LANGUAGE_MAP
                    language = LANGUAGE_MAP.get(lang_ext, "unknown")
                    filtered = code_filter(file_raw, language, level)
                    raw = file_raw
                except (FileNotFoundError, PermissionError) as e:
                    return f"Error: {e}"
            else:
                return "Error: pyrtk read requires a file path"

        elif main_cmd == "err":
            filtered = _filter_errors(stdout, stderr)

        elif main_cmd == "test":
            filtered = _filter_test_output(raw, code)

    except Exception as e:
        write_log("FILTER ERROR", f"{main_cmd} - filter failed: {str(e)}")
        filtered = raw

    _log(command, cwd, raw, filtered, exec_ms)
    return filtered


@mcp.tool()
def rtk_gain() -> str:
    """Return token savings summary from MemCore.

    Use this to check how many tokens pyrtk has saved in this project.
    """
    write_log("GAIN", "rtk_gain - query savings")
    try:
        res = requests.get(
            f"http://localhost:{_MEMCORE_PORT}/agentmemory/gain",
            timeout=3,
        )
        if res.status_code == 200:
            d = res.json()
            return (
                f"pyrtk savings:\n"
                f"  Commands processed : {d.get('total_commands', 0)}\n"
                f"  Tokens saved       : {d.get('total_saved_t', 0):,}\n"
                f"  Average efficiency : {d.get('avg_pct', 0.0):.1f}%"
            )
        return f"MemCore error: HTTP {res.status_code}"
    except requests.exceptions.RequestException as e:
        return f"MemCore unreachable on port {_MEMCORE_PORT}: {e}"


@mcp.tool()
def rtk_passthrough(command: str, cwd: str = ".") -> str:
    """Run a command with zero filtering — full raw output.

    Use when a filter is too aggressive or you need exact command output.
    Output is still logged to MemCore for tracking.

    Args:
        command: Full shell command string.
        cwd:     Working directory.
    """
    err = _validate_cwd(cwd)
    if err:
        return err

    try:
        import platform
        is_windows = platform.system() == "Windows"
        args = [a.strip('"\'') for a in shlex.split(command, posix=not is_windows)]
    except ValueError as e:
        return f"Error: could not parse command: {e}"

    t0 = time.time()
    stdout, stderr, code = execute_command(args, cwd=cwd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = stdout + stderr
    write_log("PASSTHROUGH", f"rtk_passthrough - Cmd: \"{_scrub(command)}\", Exec: {exec_ms}ms")
    _log(command, cwd, raw, raw, exec_ms)

    return raw


@mcp.tool()
def rtk_discover(since_hours: int = 24) -> str:
    """Identify commands run in this session that bypassed pyrtk.

    Queries MemCore for recent command history and compares against
    the list of commands pyrtk knows how to filter. Helps you spot
    missed savings.

    Args:
        since_hours: How many hours of history to check (default: 24).
    """
    _COVERED = {
        "git", "pytest", "ruff", "grep", "rg", "find",
        "pip", "uv", "docker", "ls", "read", "err", "test",
    }

    write_log("DISCOVER", f"rtk_discover - hours: {since_hours}")
    try:
        res = requests.get(
            f"http://localhost:{_MEMCORE_PORT}/agentmemory/command/history",
            params={"hours": since_hours},
            timeout=3,
        )
        if res.status_code != 200:
            return f"MemCore error: HTTP {res.status_code}"

        history = res.json().get("commands", [])
    except requests.exceptions.RequestException as e:
        return f"MemCore unreachable: {e}"

    if not history:
        return f"No commands logged in the last {since_hours}h."

    rtk_cmds = {r["command"].split()[0] for r in history if r.get("command")}
    bypassed = _COVERED - rtk_cmds

    if not bypassed:
        return f"All tracked commands routed through pyrtk in last {since_hours}h ✓"

    lines = [f"Commands bypassing pyrtk in last {since_hours}h ({len(bypassed)} found):\n"]
    for cmd in sorted(bypassed):
        lines.append(f"  {cmd}")
    lines.append(
        "\nFix: ensure AGENTS.md instructs agy to use rtk_run_command for these commands."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    write_log("pyrtk", "MCP server initialized successfully")
    mcp.run()
