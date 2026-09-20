# src/pyrtk/mcp_server.py
from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import threading
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

from .core.dispatcher import dispatch_command
from .core.utils import estimate_tokens, execute_command, get_execution_env, scrub_secrets


# Custom logging matching memcore.log style with automatic rotation
def write_log(tag: str, msg: str) -> None:
    """Write log messages to pyrtk.log matching MemCore format with rotation."""
    try:
        now_str = datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        local_log = Path(__file__).parent.parent.parent / "pyrtk.log"
        if local_log.exists():
            log_path = local_log
        else:
            log_dir = Path.home() / ".pyrtk"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "pyrtk.log"

        if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
            rot_path = log_path.with_suffix(".log.1")
            if rot_path.exists():
                rot_path.unlink()
            log_path.rename(rot_path)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now_str}] [{tag}] {msg}\n")
    except Exception:
        pass


mcp = FastMCP("pyrtk")

_MEMCORE_PORT = os.getenv("MEMCORE_PORT", "3111")


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
    """Build and fire the MemCore tracking payload asynchronously and save locally."""
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = round((saved / inp * 100) if inp > 0 else 0.0, 1)

    project = Path(cwd).resolve().name
    now_str = datetime.datetime.now(datetime.UTC).isoformat() + "Z"
    clean_cmd = scrub_secrets(command)

    # Persist locally in SQLite registry
    from .registry import registry
    registry.log_command(
        timestamp=now_str,
        project=project,
        command=clean_cmd,
        input_t=inp,
        output_t=out,
        saved_t=saved,
        pct=pct,
        exec_ms=exec_ms,
    )

    payload = {
        "timestamp": now_str,
        "project": project,
        "command": clean_cmd,
        "input_t": inp,
        "output_t": out,
        "saved_t": saved,
        "pct": pct,
        "exec_ms": exec_ms,
    }
    # Log locally in pyrtk.log
    write_log("CMD", f"rtk_run_command - Cmd: \"{clean_cmd}\", Saved: {saved} tokens ({pct}%), Exec: {exec_ms}ms")
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
def rtk_run_command(command: str, cwd: str = ".", background: bool = False) -> str:
    """Run a shell command with automatic token compression and MemCore logging.

    Supports: git, pytest, cargo, ruff, grep/rg, find, pip/uv, docker, ls,
              read (source file), err (generic errors-only), test (generic failures-only).
    Falls back to raw output for any unrecognised command.

    Args:
        command: Full shell command string. Quoted arguments are supported.
        cwd:     Working directory for the command. Defaults to current directory.
        background: If True, run detached in background and return PID and handle.

    Returns:
        Compressed command output as a string (or JSON with background handle if detached).
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

    # Auto-detect persistent background services
    if not background:
        bg_patterns = [
            r"\b(npm|yarn|pnpm|bun)\s+(run\s+)?(dev|start|watch)\b",
            r"\bdocker\s+compose\s+up\b",
            r"\bdocker-compose\s+up\b",
            r"\b(uvicorn|gunicorn|fastapi\s+dev)\b",
            r"\bpython\s+-m\s+http\.server\b",
            r"\bnode\s+--watch\b",
        ]
        if any(re.search(pat, command) for pat in bg_patterns):
            background = True

    if background:
        log_dir = Path(cwd).resolve() / ".pyrtk_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        import uuid
        h_suffix = uuid.uuid4().hex[:8]
        stdout_path = log_dir / f"{args[0]}_{h_suffix}_stdout.log"
        stderr_path = log_dir / f"{args[0]}_{h_suffix}_stderr.log"

        creationflags = 0
        start_new_session = False
        import sys
        if sys.platform == "win32":
            import subprocess
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            start_new_session = True

        env = get_execution_env(cwd)

        try:
            import subprocess
            with open(stdout_path, "wb") as f_out, open(stderr_path, "wb") as f_err:
                proc = subprocess.Popen(
                    args,
                    stdout=f_out,
                    stderr=f_err,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                    cwd=cwd,
                    env=env,
                    creationflags=creationflags,
                    start_new_session=start_new_session,
                )
            from .registry import registry
            handle_id = registry.register(proc, args, str(stdout_path), str(stderr_path))
            write_log(
                "BACKGROUND",
                f'Started background process: command="{command}", pid={proc.pid}, handle_id={handle_id}',
            )
            return json.dumps({"handle_id": handle_id, "pid": proc.pid})
        except Exception as ex:
            write_log("BACKGROUND ERROR", f"Failed to start background process: {ex}")
            return json.dumps({"error": f"Failed to start background process: {ex}"})

    # Synchronous execution via unified dispatcher
    res = dispatch_command(args, cwd=cwd)
    _log(command, cwd, res.raw, res.filtered, res.exec_ms)
    return res.filtered


@mcp.tool()
def rtk_kill_background(handle_id: str) -> str:
    """Terminate a running background process by handle_id.

    Args:
        handle_id: The handle ID of the background process to terminate.

    Returns:
        JSON string indicating whether the process was successfully terminated.
    """
    write_log("KILL", f"rtk_kill_background - handle_id: {handle_id}")
    try:
        from .registry import registry
        success = registry.terminate(handle_id)
        return json.dumps({"handle_id": handle_id, "killed": success})
    except KeyError:
        return json.dumps({"error": f"Unknown handle_id: {handle_id}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to terminate process: {e}"})


@mcp.tool()
def rtk_gain() -> str:
    """Return token savings summary from MemCore (or local SQLite fallback).

    Use this to check how many tokens pyrtk has saved in this project.
    """
    write_log("GAIN", "rtk_gain - query savings")
    try:
        res = requests.get(
            f"http://localhost:{_MEMCORE_PORT}/agentmemory/gain",
            timeout=2,
        )
        if res.status_code == 200:
            d = res.json()
            return (
                f"pyrtk savings (MemCore):\n"
                f"  Commands processed : {d.get('total_commands', 0)}\n"
                f"  Tokens saved       : {d.get('total_saved_t', 0):,}\n"
                f"  Average efficiency : {d.get('avg_pct', 0.0):.1f}%"
            )
    except requests.exceptions.RequestException:
        pass

    # Fallback to local SQLite registry
    from .registry import registry
    d = registry.get_local_stats()
    return (
        f"pyrtk savings (Local SQLite):\n"
        f"  Commands processed : {d.get('total_commands', 0)}\n"
        f"  Tokens saved       : {d.get('total_saved_t', 0):,}\n"
        f"  Average efficiency : {d.get('avg_pct', 0.0):.1f}%"
    )


@mcp.tool()
def rtk_passthrough(command: str, cwd: str = ".") -> str:
    """Run a command with zero filtering - full raw output.

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
    write_log("PASSTHROUGH", f"rtk_passthrough - Cmd: \"{scrub_secrets(command)}\", Exec: {exec_ms}ms")
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
        "git", "pytest", "cargo", "ruff", "grep", "rg", "find",
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


@mcp.tool()
def rtk_check_background(handle_id: str, tail_lines: int = 20) -> str:
    """Check the status of a background process by handle_id.

    Args:
        handle_id: The handle_id returned when the command was launched.
        tail_lines: Number of lines to tail from stdout/stderr. Defaults to 20.

    Returns:
        JSON string representing the process status.
    """
    try:
        from .registry import registry
        entry = registry.get(handle_id)
    except KeyError:
        return json.dumps({"error": f"Unknown handle_id: {handle_id}"})

    import psutil
    proc = entry.live_handle

    if proc is not None:
        exit_code = proc.poll()
        alive = exit_code is None
        if exit_code is not None:
            # Clean exit detection - write-through ended_at and exit_code
            import time
            registry.update_status(handle_id, time.time(), exit_code)
    else:
        # Check by pid with start time verification to guard against PID recycling
        alive = False
        exit_code = entry.exit_code
        try:
            p = psutil.Process(entry.pid)
            if abs(p.create_time() - entry.started_at) < 3.0:
                alive = p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        if not alive and exit_code is None:
            import time
            registry.update_status(handle_id, time.time(), -1)
            exit_code = -1

    stdout_tail = _tail(entry.stdout_log, tail_lines)
    stderr_tail = _tail(entry.stderr_log, tail_lines)

    return json.dumps({
        "pid": entry.pid,
        "alive": alive,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "exit_code": exit_code,
    })


def _tail(path: str, n: int) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, max(8192, 128 * n))
            f.seek(-block, os.SEEK_END)
            lines = f.read().decode("utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
    except Exception:
        return ""


@mcp.tool()
def rtk_retrieve(ref: str) -> str:
    """Retrieve the original uncompressed block corresponding to a CCR ref key.

    Args:
        ref: The cache reference string (e.g. ccr_<hash>).

    Returns:
        JSON string representing the original cache content.
    """
    try:
        from .registry import registry
        data = registry.ccr_retrieve(ref)
        return json.dumps(data, indent=2)
    except KeyError as e:
        return json.dumps({"error": str(e)})


def main() -> None:
    write_log("pyrtk", "MCP server initialized successfully")
    mcp.run()


if __name__ == "__main__":
    main()
