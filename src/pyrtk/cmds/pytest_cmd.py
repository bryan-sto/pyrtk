# src/pyrtk/cmds/pytest_cmd.py
from ..core.utils import execute_command, strip_ansi
from ..tracker import track
import time
import re

def run(args: list[str], verbose: bool = False):
    cmd = ["pytest"] + args
    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)
    
    raw = strip_ansi(stdout + stderr)
    filtered = _filter_pytest(raw)
    
    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)
    
    if code != 0:
        exit(code)

def _filter_pytest(raw: str) -> str:
    lines = raw.splitlines()
    failures = []
    in_failures_section = False
    
    for line in lines:
        if "=== FAILURES ===" in line:
            in_failures_section = True
            failures.append(line)
            continue
        if "=== ERRORS ===" in line:
            # NOTE: Reset rather than continue accumulating — ERRORS is a
            # distinct section from FAILURES; without this, if ERRORS appears
            # after FAILURES, lines bleed together.
            in_failures_section = True
            failures.append("")  # blank separator
            failures.append(line)
            continue
        if re.match(r'===+ .* in \d+\.\d+s ===+', line):
            # Summary line
            failures.append(line)
            break
        if in_failures_section:
            failures.append(line)
            
    if not failures:
        # Check if there is a summary line at least
        summary = [l for l in lines if "passed" in l or "failed" in l]
        if summary:
            return summary[-1]
        return "all tests passed" if "failed" not in raw.lower() else raw[:400]
        
    # Return at most 50 lines of failures to avoid token bloat
    return "\n".join(failures[:50])
