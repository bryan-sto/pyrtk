# src/pyrtk/core/utils.py
import subprocess
import re
import os

# NOTE: Compiled once at module load — strip_ansi() is called on every command
# output, so recompiling per-call adds measurable overhead across a session.
_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# NOTE: RTK_TIMEOUT configures subprocess timeout (seconds). Default 120s to
# accommodate slow pytest runs, docker build, and other long-running commands.
_TIMEOUT: int = int(os.getenv("RTK_TIMEOUT", "120"))


def execute_command(cmd: list[str], cwd: str = ".") -> tuple[str, str, int]:
    """Run a shell command safely and return (stdout, stderr, exit_code)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as e:
        return "", f"Error: Command timed out after {_TIMEOUT}s. {str(e)}", 124
    except Exception as e:
        return "", f"Error running command: {str(e)}", 1


def strip_ansi(text: str) -> str:
    """Strips ANSI escape characters from output text."""
    return _ANSI_RE.sub('', text)


def estimate_tokens(text: str) -> int:
    """Estimates token usage using character heuristic."""
    return max(1, len(text) // 4)
