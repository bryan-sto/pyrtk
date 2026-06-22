# src/pyrtk/cmds/ls_cmd.py
from ..core.utils import execute_command
from pathlib import Path

def run(args: list[str], verbose: bool = False):
    target = Path(args[0]) if args else Path(".")
    if not target.exists():
        print(f"Path not found: {target}")
        return
    if target.is_file():
        print(f"{target.name} ({target.stat().st_size}B)")
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
    print("\n".join(output) if output else "empty directory")
