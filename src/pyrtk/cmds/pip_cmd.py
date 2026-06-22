# src/pyrtk/cmds/pip_cmd.py
from ..core.utils import execute_command, strip_ansi
from ..tracker import track
import time


def run(args: list[str], verbose: bool = False):
    cmd = ["pip"] + args
    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    sub = args[0] if args else ""
    filtered = _filter_pip_list(raw) if sub == "list" else raw

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        exit(code)


def _filter_pip_list(raw: str) -> str:
    """Compact pip list — one package per line with aligned name/version columns."""
    lines = raw.splitlines()
    # Skip header rows ("Package", "---")
    pkgs = [
        l for l in lines
        if l.strip() and not l.startswith("-") and not l.lower().startswith("package")
    ]
    if not pkgs:
        return raw[:300]

    compact = []
    for pkg in pkgs:
        parts = pkg.split()
        if len(parts) >= 2:
            compact.append(f"{parts[0]:<30} {parts[1]}")
        else:
            compact.append(pkg)

    return f"{len(compact)} packages\n" + "\n".join(compact)
