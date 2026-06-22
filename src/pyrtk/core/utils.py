# src/pyrtk/core/utils.py
import subprocess
import re

def execute_command(cmd: list[str], cwd: str = ".") -> tuple[str, str, int]:
    """Run a shell command safely and return (stdout, stderr, exit_code)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=cwd, stdin=subprocess.DEVNULL)
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as e:
        return "", f"Error: Command timed out after 10 seconds. {str(e)}", 124
    except Exception as e:
        return "", f"Error running command: {str(e)}", 1

def strip_ansi(text: str) -> str:
    """Strips ANSI escape characters from output text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def estimate_tokens(text: str) -> int:
    """Estimates token usage using character heuristic."""
    return max(1, len(text) // 4)
