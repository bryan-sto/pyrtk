# src/pyrtk/mcp_server.py
from mcp.server.fastmcp import FastMCP
import subprocess
import requests
import datetime
import time
import os
from pathlib import Path
from .core.utils import execute_command, estimate_tokens

mcp = FastMCP("pyrtk")

@mcp.tool()
def rtk_run_command(command: str, cwd: str = ".") -> str:
    """Run shell command with auto token compression and logging."""
    t0 = time.time()
    
    args = command.split()
    if not args:
        return ""
        
    main_cmd = args[0]
    cmd_args = args[1:]
    
    stdout, stderr, code = execute_command(args, cwd=cwd)
    exec_ms = int((time.time() - t0) * 1000)
    
    raw = stdout + stderr
    
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
    elif main_cmd == "pytest":
        from .cmds.pytest_cmd import _filter_pytest
        filtered = _filter_pytest(raw)
    elif main_cmd == "docker":
        from .cmds.docker_cmd import _filter_ps, dedup
        sub = cmd_args[0] if cmd_args else ""
        if sub == "ps":
            filtered = _filter_ps(raw)
        elif sub == "logs":
            filtered = dedup(raw)
        else:
            filtered = raw
    elif main_cmd == "ls":
        from .cmds.ls_cmd import run
        target = Path(cmd_args[0]) if cmd_args else Path(".")
        if not target.exists():
            return f"Path not found: {target}"
        if target.is_file():
            return f"{target.name} ({target.stat().st_size}B)"
        dirs = []
        files_count = 0
        for item in target.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                subfiles = sum(1 for _ in item.glob('*') if _.is_file())
                dirs.append(f"{item.name}/ ({subfiles} files)")
            elif item.is_file() and not item.name.startswith('.'):
                files_count += 1
        output = []
        if dirs:
            output.extend(dirs)
        if files_count:
            output.append(f"files: {files_count} file(s) in root")
        filtered = "\n".join(output) if output else "empty directory"
    else:
        filtered = raw

    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = (saved / inp * 100) if inp > 0 else 0.0
    
    project = Path(cwd).resolve().name
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "project": project,
        "command": command,
        "input_t": inp,
        "output_t": out,
        "saved_t": saved,
        "pct": pct,
        "exec_ms": exec_ms
    }
    
    port = os.getenv("MEMCORE_PORT", "3111")
    try:
        requests.post(f"http://localhost:{port}/agentmemory/command/log", json=payload, timeout=2)
    except requests.exceptions.RequestException:
        pass
        
    return filtered

if __name__ == "__main__":
    mcp.run()
