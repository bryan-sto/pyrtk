# src/pyrtk/core/utils.py
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
_TIMEOUT = int(os.getenv("RTK_TIMEOUT", "120"))

_SECRET_PATTERNS = [
    # Authorization: Bearer <token> or Bearer <token>
    (
        re.compile(r"""(?i)\b(?:authorization:\s*)?bearer\s+(['"]?)([^\s'"]+)\1"""),
        r"Bearer [REDACTED]",
    ),
    # Key-value pairs: token=xyz, password: xyz, "api_key": "xyz"
    (
        re.compile(
            r"""(?i)\b(authorization|token|password|secret|api[_-]?key|auth)"""
            r"""(?:\s*[:=]\s*|\s+)(['"]?)([^\s'"]+)\2""",
            re.VERBOSE,
        ),
        r"\1 \2[REDACTED]\2",
    ),
    # Basic auth in URLs: http://user:pass@host
    (
        re.compile(r"""(?i)(https?://[^:\s]+:)([^@\s]+)(@)"""),
        r"\1[REDACTED]\3",
    ),
    # curl -u user:pass or --user user:pass
    (
        re.compile(r"""(?i)(-u|--user)\s+([^:\s]+:)(\S+)"""),
        r"\1 \2[REDACTED]",
    ),
    # Private key blocks
    (
        re.compile(r"-----BEGIN[ A-Z0-9_-]+PRIVATE KEY-----.*?-----END[ A-Z0-9_-]+PRIVATE KEY-----", re.DOTALL),
        "[REDACTED PRIVATE KEY]",
    ),
]


def scrub_secrets(text: str) -> str:
    """Remove credentials, tokens, passwords, and private keys from text."""
    result = text
    for pat, repl in _SECRET_PATTERNS:
        result = pat.sub(repl, result)
    return result


def resolve_executable(cmd_name: str, path: str | None = None) -> str:
    """Resolve an executable name to its full path across Windows (.exe/.cmd/.bat) and POSIX."""
    resolved = shutil.which(cmd_name, path=path)
    return resolved if resolved else cmd_name


def get_execution_env(cwd: str = ".") -> dict[str, str]:
    """Prepare an execution environment with proper PATH and virtualenv settings."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["LC_ALL"] = "en_US.UTF-8"

    target_venv = os.path.join(cwd, ".venv")
    if os.path.exists(target_venv):
        scripts_dir = os.path.join(target_venv, "Scripts" if sys.platform == "win32" else "bin")
        if os.path.exists(scripts_dir):
            env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = os.path.abspath(target_venv)
        else:
            env.pop("VIRTUAL_ENV", None)

    # Ensure current working directory is in PYTHONPATH so local packages/src resolve
    abs_cwd = os.path.abspath(cwd)
    existing_pythonpath = env.get("PYTHONPATH", "")
    if abs_cwd not in existing_pythonpath.split(os.pathsep):
        env["PYTHONPATH"] = abs_cwd + (os.pathsep + existing_pythonpath if existing_pythonpath else "")

    return env


def execute_command(cmd: list[str], cwd: str = ".") -> tuple[str, str, int]:
    """Run a shell command safely and return (stdout, stderr, exit_code)."""
    if not cmd:
        return "", "", 0

    try:
        env = get_execution_env(cwd)

        # Resolve command executable (handles Windows .cmd, .bat, and venv binaries)
        resolved_cmd = resolve_executable(cmd[0], path=env.get("PATH"))
        cmd_to_run = [resolved_cmd] + cmd[1:]

        result = subprocess.run(
            cmd_to_run,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            env=env,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as e:
        return "", f"Error: Command timed out after {_TIMEOUT}s. {str(e)}", 124
    except FileNotFoundError as e:
        return "", f"Error: Command executable not found: {str(e)}", 127
    except Exception as e:
        return "", f"Error running command: {str(e)}", 1


def strip_ansi(text: str) -> str:
    """Strips ANSI escape characters from output text."""
    return _ANSI_RE.sub('', text)


def estimate_tokens(text: str) -> int:
    """Estimates token usage using character heuristic (ceil(len/4))."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)
