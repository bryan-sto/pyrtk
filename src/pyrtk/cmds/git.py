# src/pyrtk/cmds/git.py
from __future__ import annotations

import re

_MAX_PATCH_CHARS = 12000


def split_git_subcommand(args: list[str]) -> tuple[list[str], str, list[str]]:
    """Split git args into (prefix_with_leading_flags, subcommand, remaining_args)."""
    if not args or args[0] != "git":
        return args, "", []

    idx = 1
    while idx < len(args):
        arg = args[idx]
        if arg == "-C" and idx + 1 < len(args):
            idx += 2
            continue
        if arg.startswith("-C") and len(arg) > 2:
            idx += 1
            continue
        break

    if idx >= len(args):
        return args, "", []
    return args[:idx], args[idx], args[idx + 1 :]


def get_optimised_git_command(args: list[str]) -> list[str]:
    """Intercepts git status, diff, or log to return the optimised command array."""
    prefix, sub, rest = split_git_subcommand(args)
    if not sub:
        return args

    if sub == "status":
        return prefix + ["status", "--porcelain", "-b"] + rest
    elif sub == "diff":
        has_stat_option = any(arg in rest for arg in ("--stat", "--name-only", "--name-status", "-p", "--patch"))
        if not has_stat_option:
            return prefix + ["diff", "--stat"] + rest
        return args
    elif sub == "log":
        has_format = any(a.startswith("--format") or a.startswith("--pretty") or a == "--oneline" for a in rest)
        if not has_format:
            return prefix + ["log", "--oneline"] + rest
        return args
    return args


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy git - compact status, log, diff, push output."""
    from ..core.dispatcher import run_cli_command

    run_cli_command("git", args, verbose=verbose)


def _filter_status(raw: str) -> str:
    if not raw.strip():
        return "clean"
    branch_header: str | None = None
    modified = []
    untracked_count = 0
    for line in raw.splitlines():
        if line.startswith("## "):
            branch_header = line.strip()
            continue
        if len(line) < 3:
            continue
        status = line[:2]
        file_path = line[3:]
        if status == "??":
            untracked_count += 1
        else:
            modified.append(f"{status.strip()} {file_path}")

    parts = []
    if branch_header:
        parts.append(branch_header)
    if modified:
        if len(modified) <= 15:
            parts.append(f"modified: {', '.join(modified)}")
        else:
            parts.append(f"modified: {', '.join(modified[:15])} ... (+{len(modified) - 15} more files)")
    if untracked_count:
        parts.append(f"untracked: {untracked_count} file(s)")
    if branch_header and not modified and not untracked_count:
        parts.append("clean")
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
            if len(raw) > _MAX_PATCH_CHARS:
                return raw[:_MAX_PATCH_CHARS] + f"\n[... diff truncated at {_MAX_PATCH_CHARS} chars]"
            return raw
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
    if sub == "commit":
        sha = re.search(r"\[[^\]]+\s+([0-9a-f]{7,40})\]", raw) or re.search(r"\b([0-9a-f]{7,40})\b", raw)
        return f"ok {sha.group(1) if sha else 'commit'}"
    if sub == "add":
        return "ok add"
    return "ok"
