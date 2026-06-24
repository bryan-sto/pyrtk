# src/pyrtk/core/utils.py
from __future__ import annotations

import os
import re
import subprocess

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
_TIMEOUT = int(os.getenv("RTK_TIMEOUT", "120"))


def execute_command(cmd: list[str], cwd: str = ".") -> tuple[str, str, int]:
    """Run a shell command safely and return (stdout, stderr, exit_code)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
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
    """Estimates token usage using character heuristic."""
    return len(text) // 4
