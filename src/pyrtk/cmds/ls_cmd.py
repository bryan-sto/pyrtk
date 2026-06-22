# src/pyrtk/cmds/ls_cmd.py
from ..core.utils import execute_command, estimate_tokens
from ..tracker import track
from pathlib import Path
import time


def run(args: list[str], verbose: bool = False):
    cmd = ["ls"] + args
    t0 = time.time()

    target = Path(args[0]) if args else Path(".")
    if not target.exists():
        print(f"Path not found: {target}")
        exit(1)

    if target.is_file():
        filtered = f"{target.name} ({target.stat().st_size}B)"
        print(filtered)
        exec_ms = int((time.time() - t0) * 1000)
        track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", filtered, filtered, exec_ms)
        return

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

    print(filtered)
    exec_ms = int((time.time() - t0) * 1000)
    # NOTE: ls is always local Python — raw == filtered, no shell output to compare.
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", filtered, filtered, exec_ms)
