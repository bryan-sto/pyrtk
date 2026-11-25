# src/pyrtk/core/dispatcher.py
from __future__ import annotations

import itertools
import json
import os
import shutil
import sys
import time
import uuid
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
from .utils import execute_command, scrub_secrets, strip_ansi


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
        uid = uuid.uuid4().hex[:6]
        filename = f"{int(time.time())}_{uid}_{main_cmd}.log"
        log_file = tee_dir / filename
        log_file.write_text(scrub_secrets(raw), encoding="utf-8", errors="replace")
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
        is_uv_pip = main_cmd == "uv" and sub == "pip"
        effective_sub = cmd_args[1] if is_uv_pip and len(cmd_args) > 1 else sub
        if effective_sub == "list":
            extra_args = cmd_args[2:] if is_uv_pip else cmd_args[1:]
            tool = "uv" if shutil.which("uv") else "pip"
            base_cmd = [tool, "pip", "list"] if tool == "uv" else ["pip", "list"]
            clean_extra: list[str] = []
            skip_next = False
            for a in extra_args:
                if skip_next:
                    skip_next = False
                    continue
                if a == "--format":
                    skip_next = True
                    continue
                if a.startswith("--format="):
                    continue
                clean_extra.append(a)
            exec_cmd = base_cmd + ["--format", "json"] + clean_extra
        elif main_cmd == "pip":
            tool = "uv" if shutil.which("uv") else "pip"
            if tool == "uv":
                exec_cmd = ["uv", "pip"] + cmd_args
    elif main_cmd in ("grep", "rg"):
        tool = "rg" if shutil.which("rg") else "grep"
        exec_cmd = [tool] + cmd_args

    # Execute
    t0 = time.time()

    # Special handling for internal commands (ls, read, and Windows find fallback)
    if main_cmd == "ls":
        if cmd_args and cmd_args[0].startswith("-"):
            stdout, stderr, code = execute_command(exec_cmd, cwd=cwd)
        else:
            target = Path(cmd_args[0]) if cmd_args else Path(cwd)
            if not target.is_absolute():
                target = Path(cwd) / target
            if not target.exists():
                exec_ms = int((time.time() - t0) * 1000)
                return CommandResult(
                    raw="",
                    filtered=f"Path not found: {target}",
                    exit_code=1,
                    exec_ms=exec_ms,
                )
            if target.is_file():
                filtered = f"{target.name} ({target.stat().st_size}B)"
                exec_ms = int((time.time() - t0) * 1000)
                return CommandResult(raw=filtered, filtered=filtered, exit_code=0, exec_ms=exec_ms)
            try:
                items = sorted(target.iterdir())
            except PermissionError:
                exec_ms = int((time.time() - t0) * 1000)
                return CommandResult(
                    raw="",
                    filtered=f"Permission denied: {target}",
                    exit_code=1,
                    exec_ms=exec_ms,
                )
            dirs, files_count = [], 0
            for item in items:
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
    elif main_cmd == "read":
        if cmd_args:
            filepath = Path(cwd) / cmd_args[0] if not Path(cmd_args[0]).is_absolute() else Path(cmd_args[0])
            level_str = os.getenv("RTK_READ_LEVEL", "minimal")
            idx = 1
            while idx < len(cmd_args):
                arg = cmd_args[idx]
                if arg in ("none", "minimal", "aggressive"):
                    level_str = arg
                    idx += 1
                elif arg == "--level" and idx + 1 < len(cmd_args):
                    level_str = cmd_args[idx + 1]
                    idx += 2
                elif arg.startswith("--level="):
                    level_str = arg.split("=", 1)[1]
                    idx += 1
                else:
                    idx += 1

            try:
                level = FilterLevel(level_str)
            except ValueError:
                level = FilterLevel.MINIMAL

            if not filepath.exists():
                exec_ms = int((time.time() - t0) * 1000)
                return CommandResult(
                    raw="",
                    filtered=f"Error: file not found: {cmd_args[0]}",
                    exit_code=1,
                    exec_ms=exec_ms,
                )
            if not filepath.is_file():
                exec_ms = int((time.time() - t0) * 1000)
                return CommandResult(
                    raw="",
                    filtered=f"Error: not a file: {cmd_args[0]}",
                    exit_code=1,
                    exec_ms=exec_ms,
                )

            try:
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
            except PermissionError as e:
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

    # Save tee log on failure if output is significant (grep exit 1 is normal no-match)
    if code != 0 and not (main_cmd in ("grep", "rg") and code == 1) and len(raw) > 200:
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


def run_cli_command(
    main_cmd: str,
    args: list[str],
    verbose: bool = False,
    cwd: str = ".",
    allowed_exit_codes: tuple[int, ...] = (0,),
    error_to_stderr: bool = False,
    empty_ok_output: str | None = None,
    empty_err_output: str | None = None,
) -> CommandResult:
    """Execute, filter, print, and track a CLI command via dispatch_command."""
    from .. import tracker

    res = dispatch_command([main_cmd] + args, cwd=cwd)

    if error_to_stderr and res.exit_code not in allowed_exit_codes:
        print(res.filtered, file=sys.stderr)
        raise SystemExit(res.exit_code)

    if verbose:
        pct = int(max(0, len(res.raw) - len(res.filtered)) / max(len(res.raw), 1) * 100)
        print(f"[pyrtk] {main_cmd} - {pct}% saved", file=sys.stderr)

    output = res.filtered
    if not output.strip():
        if res.exit_code not in allowed_exit_codes and empty_err_output is not None:
            output = empty_err_output.format(code=res.exit_code)
        elif res.exit_code in allowed_exit_codes and empty_ok_output is not None:
            output = empty_ok_output

    print(output)

    orig_args = args if main_cmd in ("err", "test") else [main_cmd] + args
    orig_cmd = " ".join(orig_args)
    rtk_cmd = f"pyrtk {' '.join([main_cmd] + args)}"
    tracker.track(orig_cmd, rtk_cmd, res.raw, res.filtered, res.exec_ms, cwd=cwd)

    if res.exit_code not in allowed_exit_codes:
        raise SystemExit(res.exit_code)

    return res
