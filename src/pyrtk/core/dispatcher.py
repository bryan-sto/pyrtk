# src/pyrtk/core/dispatcher.py
from __future__ import annotations

import itertools
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..cmds.cargo_cmd import _filter_cargo_build, _filter_cargo_clippy, _filter_cargo_test
from ..cmds.docker_cmd import _filter_ps
from ..cmds.err_cmd import _filter_errors
from ..cmds.find_cmd import _filter_find, _python_find
from ..cmds.git import _filter_diff, _filter_log, _filter_simple, _filter_status, get_optimised_git_command
from ..cmds.grep_cmd import _filter_grep
from ..cmds.pip_cmd import _filter_list as _pip_list
from ..cmds.pip_cmd import _filter_show as _pip_show
from ..cmds.pytest_cmd import _filter_pytest
from ..cmds.read_cmd import LANGUAGE_MAP
from ..cmds.ruff_cmd import _filter_check_json, _filter_check_text
from ..cmds.ruff_cmd import _filter_format as _ruff_format
from ..cmds.test_cmd import _filter_test_output
from .filter import FilterLevel, code_filter, dedup
from .json_compress import compress_json
from .utils import execute_command, strip_ansi


@dataclass(frozen=True)
class CommandResult:
    raw: str
    filtered: str
    exit_code: int
    exec_ms: int
    tee_path: str | None = None


def _write_tee_log(main_cmd: str, raw: str, cwd: str = ".") -> str | None:
    """Save full unfiltered output to ~/.pyrtk/tee/ on failure for recovery."""
    try:
        tee_dir = Path.home() / ".pyrtk" / "tee"
        tee_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time())}_{main_cmd}.log"
        log_file = tee_dir / filename
        log_file.write_text(raw, encoding="utf-8", errors="replace")
        return str(log_file)
    except Exception:
        return None


def dispatch_command(args: list[str], cwd: str = ".") -> CommandResult:
    """Execute and filter a command through pyrtk's unified pipeline."""
    if not args:
        return CommandResult(raw="", filtered="", exit_code=0, exec_ms=0)

    main_cmd = args[0]
    cmd_args = args[1:]

    # Optimize command before execution if applicable
    exec_cmd = list(args)
    is_ruff_check = False

    if main_cmd == "git":
        exec_cmd = get_optimised_git_command(args)
    elif main_cmd == "docker":
        sub = cmd_args[0] if cmd_args else ""
        if sub == "ps":
            exec_cmd = ["docker", "ps", "--format", "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"] + cmd_args[1:]
    elif main_cmd == "ruff":
        sub = cmd_args[0] if cmd_args else "check"
        if sub == "check" or (sub not in ("format", "version", "help", "rule") and not sub.startswith("-")):
            is_ruff_check = True
            clean_args = [a for a in cmd_args if a != "check" and not a.startswith("--output-format")]
            exec_cmd = ["ruff", "check", "--output-format", "json"] + clean_args
    elif main_cmd in ("pip", "uv"):
        sub = cmd_args[0] if cmd_args else ""
        effective_sub = cmd_args[1] if main_cmd == "uv" and sub == "pip" and len(cmd_args) > 1 else sub
        if effective_sub == "list":
            tool = "uv" if shutil.which("uv") else "pip"
            base_cmd = [tool, "pip", "list"] if tool == "uv" else ["pip", "list"]
            exec_cmd = base_cmd + ["--format", "json"]
    elif main_cmd in ("grep", "rg"):
        tool = "rg" if shutil.which("rg") else "grep"
        exec_cmd = [tool] + cmd_args

    # Execute
    t0 = time.time()

    # Special handling for internal commands (ls, read, and Windows find fallback)
    if main_cmd == "ls":
        target = Path(cmd_args[0]) if cmd_args else Path(cwd)
        if not target.is_absolute():
            target = Path(cwd) / target
        if target.exists() and target.is_dir():
            dirs, files_count = [], 0
            for item in sorted(target.iterdir()):
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    try:
                        children = list(itertools.islice((f for f in item.iterdir() if f.is_file()), 51))
                        label = f"{len(children)} files" if len(children) < 51 else "50+ files"
                    except PermissionError:
                        label = "no access"
                    dirs.append(f"{item.name}/ ({label})")
                elif item.is_file():
                    files_count += 1
            parts = dirs
            if files_count:
                parts.append(f"files: {files_count} file(s) in root")
            filtered = "\n".join(parts) if parts else "empty directory"
            exec_ms = int((time.time() - t0) * 1000)
            return CommandResult(raw=filtered, filtered=filtered, exit_code=0, exec_ms=exec_ms)
        else:
            stdout, stderr, code = execute_command(exec_cmd, cwd=cwd)
    elif main_cmd == "read":
        if cmd_args:
            filepath = Path(cwd) / cmd_args[0] if not Path(cmd_args[0]).is_absolute() else Path(cmd_args[0])
            level_str = "minimal"
            for a in cmd_args[1:]:
                if a in ("none", "minimal", "aggressive"):
                    level_str = a
            try:
                level = FilterLevel(level_str)
                file_raw = filepath.read_text(encoding="utf-8", errors="replace")
                max_chars = int(os.getenv("RTK_READ_MAX_CHARS", "50000"))
                was_truncated = False
                if len(file_raw) > max_chars:
                    file_raw = file_raw[:max_chars]
                    was_truncated = True

                lang_ext = filepath.suffix.lower()
                language = LANGUAGE_MAP.get(lang_ext, "unknown")
                filtered = code_filter(file_raw, language, level)
                if was_truncated:
                    filtered += f"\n\n[... file truncated at {max_chars} chars]"
                exec_ms = int((time.time() - t0) * 1000)
                return CommandResult(raw=file_raw, filtered=filtered, exit_code=0, exec_ms=exec_ms)
            except (FileNotFoundError, PermissionError) as e:
                exec_ms = int((time.time() - t0) * 1000)
                return CommandResult(raw=str(e), filtered=f"Error: {e}", exit_code=1, exec_ms=exec_ms)
        else:
            return CommandResult(raw="", filtered="Error: read requires a file path", exit_code=1, exec_ms=0)
    elif main_cmd == "find" and (
        os.name == "nt" or shutil.which("find") is None or "system32" in (shutil.which("find") or "").lower()
    ):
        paths = _python_find(cmd_args, cwd=cwd)
        raw = "\n".join(paths)
        filtered = _filter_find(raw)
        exec_ms = int((time.time() - t0) * 1000)
        return CommandResult(raw=raw, filtered=filtered, exit_code=0, exec_ms=exec_ms)
    else:
        stdout, stderr, code = execute_command(exec_cmd, cwd=cwd)

    exec_ms = int((time.time() - t0) * 1000)
    raw = strip_ansi(stdout + stderr)
    filtered = raw
    tee_path = None

    # Save tee log on failure if output is significant
    if code != 0 and len(raw) > 200:
        tee_path = _write_tee_log(main_cmd, raw, cwd)

    # Route to filter
    try:
        if main_cmd == "git":
            sub = cmd_args[0] if cmd_args else ""
            if sub == "status":
                filtered = _filter_status(raw)
            elif sub == "log":
                filtered = _filter_log(raw)
            elif sub in ("add", "commit", "push", "pull"):
                filtered = _filter_simple(raw, sub)
            elif sub == "diff":
                filtered = _filter_diff(raw, cmd_args)
            else:
                filtered = raw

        elif main_cmd == "pytest":
            filtered = _filter_pytest(raw)

        elif main_cmd == "cargo":
            sub = cmd_args[0] if cmd_args else "build"
            if sub == "test":
                filtered = _filter_cargo_test(raw, code)
            elif sub == "clippy":
                filtered = _filter_cargo_clippy(raw)
            else:
                filtered = _filter_cargo_build(raw, code)

        elif main_cmd == "ruff":
            sub = cmd_args[0] if cmd_args else "check"
            if is_ruff_check:
                filtered = _filter_check_json(strip_ansi(stdout)) or _filter_check_text(raw)
            elif sub == "format":
                filtered = _ruff_format(raw)
            else:
                filtered = raw

        elif main_cmd in ("grep", "rg"):
            if code in (0, 1):  # exit 1 is normal "no match" for grep
                filtered = _filter_grep(raw)
            else:
                filtered = raw

        elif main_cmd == "find":
            filtered = _filter_find(raw)

        elif main_cmd in ("pip", "uv"):
            sub = cmd_args[0] if cmd_args else ""
            effective_sub = cmd_args[1] if main_cmd == "uv" and sub == "pip" and len(cmd_args) > 1 else sub
            if effective_sub == "list":
                filtered = _pip_list(strip_ansi(stdout)) if stdout.strip() else _pip_list(raw)
            elif effective_sub == "show":
                filtered = _pip_show(strip_ansi(stdout)) if stdout.strip() else _pip_show(raw)
            else:
                filtered = raw

        elif main_cmd == "docker":
            sub = cmd_args[0] if cmd_args else ""
            if sub == "ps":
                filtered = _filter_ps(raw)
            elif sub == "logs":
                filtered = dedup(raw)
            else:
                filtered = raw

        elif main_cmd == "err":
            filtered = _filter_errors(stdout, stderr)

        elif main_cmd == "test":
            filtered = _filter_test_output(raw, code)

    except Exception:
        filtered = raw

    # Auto-compress JSON output from commands (excluding read)
    if main_cmd != "read":
        try:
            stripped = filtered.strip()
            if stripped and stripped[0] in ("{", "["):
                json_data = json.loads(stripped)
                res = compress_json(json_data)
                filtered = json.dumps(res["compressed"], indent=2)
        except Exception:
            pass

    # Attach tee recovery link if created
    if tee_path:
        filtered += f"\n[full output: {tee_path}]"

    return CommandResult(raw=raw, filtered=filtered, exit_code=code, exec_ms=exec_ms, tee_path=tee_path)
