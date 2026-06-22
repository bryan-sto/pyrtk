# ponytail: mcp_server.py in root to avoid sys.path/relative import hacks
from mcp.server.fastmcp import FastMCP
import requests
import datetime
import time
import os
from pathlib import Path
from src.pyrtk.core.utils import execute_command, estimate_tokens

mcp = FastMCP("pyrtk")

@mcp.tool()
def rtk_run_command(command: str, cwd: str = ".") -> str:
    """Run shell command with auto token compression and logging."""
    t0 = time.time()
    args = command.split()
    if not args:
        return ""
    
    stdout, stderr, code = execute_command(args, cwd=cwd)
    exec_ms = int((time.time() - t0) * 1000)
    raw = stdout + stderr
    
    # ponytail: simplified direct filter checks instead of importing submodules
    main_cmd = args[0]
    cmd_args = args[1:]
    filtered = raw
    
    if main_cmd == "git":
        from src.pyrtk.cmds.git import _filter_status, _filter_log, _filter_diff, _filter_simple
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
    elif main_cmd == "pytest":
        from src.pyrtk.cmds.pytest_cmd import _filter_pytest
        filtered = _filter_pytest(raw)
    elif main_cmd == "docker":
        from src.pyrtk.cmds.docker_cmd import _filter_ps, dedup
        sub = cmd_args[0] if cmd_args else ""
        if sub == "ps":
            filtered = _filter_ps(raw)
        elif sub == "logs":
            filtered = dedup(raw)
    elif main_cmd == "ls":
        target = Path(cmd_args[0]) if cmd_args else Path(".")
        if target.exists() and target.is_dir():
            dirs = [f"{item.name}/" for item in target.iterdir() if item.is_dir() and not item.name.startswith('.')]
            files = sum(1 for item in target.iterdir() if item.is_file() and not item.name.startswith('.'))
            filtered = "\n".join(dirs) + f"\nfiles: {files} file(s) in root"
        else:
            filtered = raw

    # Log to MemCore
    port = os.getenv("MEMCORE_PORT", "3111")
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "project": Path(cwd).resolve().name,
        "command": command,
        "input_t": inp,
        "output_t": out,
        "saved_t": saved,
        "pct": (saved / inp * 100) if inp > 0 else 0.0,
        "exec_ms": exec_ms
    }
    try:
        requests.post(f"http://localhost:{port}/agentmemory/command/log", json=payload, timeout=2)
    except Exception:
        pass
        
    return filtered

if __name__ == "__main__":
    mcp.run()
