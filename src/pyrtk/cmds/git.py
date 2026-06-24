# src/pyrtk/cmds/git.py
from __future__ import annotations

import re
import sys
import time

from ..core.utils import execute_command, strip_ansi
from ..tracker import track


def run(args: list[str], verbose: bool = False) -> None:
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
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] git {sub} → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


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
    # NOTE: Match only short hashes (e.g. from git log --oneline), ignoring verbose commit header lines.
    lines = [l for l in raw.splitlines() if re.match(r'^[0-9a-f]{7,}\s', l)]
    return "\n".join(lines[:10]) if lines else raw[:200]


def _filter_diff(raw: str, args: list[str]) -> str:
    lines = raw.splitlines()
    stats = [l for l in lines if re.match(r'^\s*\d+\s+files? changed', l)]
    if stats:
        return stats[0]
    return raw[:400]


def _filter_simple(raw: str, sub: str) -> str:
    if any(w in raw.lower() for w in ("error", "rejected", "denied", "fatal")):
        return raw[:300]
    if sub == "push":
        branch = re.search(r'(HEAD -> |origin/)([^\s]+)', raw)
        return f"ok {branch.group(2) if branch else 'done'}"
    if sub in ("add", "commit"):
        sha = re.search(r'([0-9a-f]{7})', raw)
        return f"ok {sha.group(1) if sha else sub}"
    return "ok"
