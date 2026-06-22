# src/pyrtk/cmds/git.py
from ..core.utils import execute_command, strip_ansi
from ..tracker import track
import time
import re

def run(args: list[str], verbose: bool = False):
    sub = args[0] if args else ""
    cmd = ["git"] + args
    
    if sub == "status":
        exec_cmd = ["git", "status", "--porcelain"]
    elif sub == "diff" and len(args) == 1:
        exec_cmd = ["git", "diff", "--stat"]
    else:
        exec_cmd = cmd
        
    t0 = time.time()
    stdout, stderr, code = execute_command(exec_cmd)
    exec_ms = int((time.time() - t0) * 1000)
    
    raw = strip_ansi(stdout + stderr)
    
    if sub == "status":
        filtered = _filter_status(raw)
    elif sub == "log":
        filtered = _filter_log(raw)
    elif sub in ("add", "commit", "push", "pull"):
        filtered = _filter_simple(raw, sub)
    elif sub == "diff":
        filtered = _filter_diff(raw, args)
    else:
        filtered = raw
        
    if verbose:
        print(f"[pyrtk] git {sub} → {len(filtered)}/{len(raw)} chars "
              f"({100 - len(filtered)*100//max(len(raw),1)}% saved)", flush=True)
              
    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)
    
    if code != 0:
        exit(code)

def _filter_status(raw: str) -> str:
    if not raw.strip():
        return "clean"
    modified = []
    untracked_count = 0
    for line in raw.splitlines():
        if len(line) < 3:
            continue
        status = line[:2]
        file_path = line[3:]
        if status == "??":
            untracked_count += 1
        else:
            modified.append(f"{status.strip()} {file_path}")
            
    parts = []
    if modified:
        parts.append(f"modified: {', '.join(modified)}")
    if untracked_count:
        parts.append(f"untracked: {untracked_count} file(s)")
    return "\n".join(parts) if parts else "clean"

def _filter_log(raw: str) -> str:
    # NOTE: Restrict to short-hash lines only. "commit <full-sha>" prefix lines
    # are noisy and redundant when the abbreviated hash is on the same entry.
    lines = [l for l in raw.splitlines() if re.match(r'^[0-9a-f]{7,}', l)]
    return "\n".join(lines[:10]) if lines else raw[:200]

def _filter_diff(raw: str, args: list[str]) -> str:
    lines = raw.splitlines()
    stats = [l for l in lines if re.match(r'^\s*\d+\s+files? changed', l)]
    if stats:
        return stats[0]
    return raw[:400]

def _filter_simple(raw: str, sub: str) -> str:
    if "error" in raw.lower():
        return raw[:300]
    if sub == "push":
        branch = re.search(r'(HEAD -> |origin/)([^\s]+)', raw)
        return f"ok {branch.group(2) if branch else 'done'}"
    if sub in ("add", "commit"):
        sha = re.search(r'([0-9a-f]{7})', raw)
        return f"ok {sha.group(1) if sha else sub}"
    return "ok"
