# src/pyrtk/cmds/git.py
from __future__ import annotations

import re
import sys
import time

from ..core.utils import execute_command, strip_ansi
from ..tracker import track


def get_optimised_git_command(args: list[str]) -> list[str]:
    """Intercepts git status, diff, or log to return the optimised command array."""
    if not args or args[0] != "git":
        return args
    if len(args) < 2:
        return args

    sub = args[1]
    if sub == "status":
        return ["git", "status", "--porcelain"] + args[2:]
    elif sub == "diff":
        has_stat_option = any(arg in args for arg in ("--stat", "--name-only", "--name-status", "-p", "--patch"))
        if not has_stat_option:
            return ["git", "diff", "--stat"] + args[2:]
        return args
    elif sub == "log":
        has_format = any(a.startswith("--format") or a.startswith("--pretty") or a == "--oneline" for a in args)
        if not has_format:
            return ["git", "log", "--oneline"] + args[2:]
        return args
    return args


def run(args: list[str], verbose: bool = False) -> None:
    sub = args[0] if args else ""
    cmd = ["git"] + args

    exec_cmd = get_optimised_git_command(cmd)

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
        if len(modified) <= 15:
            parts.append(f"modified: {', '.join(modified)}")
        else:
            parts.append(f"modified: {', '.join(modified[:15])} ... (+{len(modified) - 15} more files)")
    if untracked_count:
        parts.append(f"untracked: {untracked_count} file(s)")
    return "\n".join(parts) if parts else "clean"


def _filter_log(raw: str) -> str:
    # Match short hashes (e.g. from git log --oneline), ignoring verbose commit header lines.
    lines = [line for line in raw.splitlines() if re.match(r'^[0-9a-f]{7,}\s', line)]
    if not lines:
        return raw[:200] if raw.strip() else "clean (no commits)"
    if len(lines) <= 15:
        return "\n".join(lines)
    return "\n".join(lines[:15]) + f"\n... +{len(lines) - 15} more commits"


def _filter_diff(raw: str, args: list[str]) -> str:
    has_stat_option = any(arg in args for arg in ("--stat", "--name-only", "--name-status", "-p", "--patch"))
    if has_stat_option:
        if any(arg in args for arg in ("-p", "--patch")):
            return raw[:400]
        return raw

    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return "clean (no changes)"
    stats = [line for line in lines if re.match(r'^\s*\d+\s+files? changed', line)]
    file_lines = [line for line in lines if "|" in line and not re.match(r'^\s*\d+\s+files? changed', line)]
    if stats:
        res = []
        for fl in file_lines[:15]:
            res.append(fl)
        if len(file_lines) > 15:
            res.append(f"  ... +{len(file_lines) - 15} more files")
        res.append(stats[0])
        return "\n".join(res)
    return "\n".join(lines[:15])


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
