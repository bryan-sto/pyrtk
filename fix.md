# pyrtk Code Review

> Full audit of the local RTK implementation. Covers correctness bugs, security, reliability, architecture, DX, and testing.

---

## Summary

| Category | Count | Priority |
|---|---|---|
| Correctness bugs | 9 | Fix now |
| Security / privacy | 2 | Fix now |
| Reliability | 4 | High |
| Dead code | 2 | Low |
| DX / config | 7 | Medium |
| Testing | 4 | Medium |
| Architecture | 4 | Low |

---

## Correctness Bugs

### 1. `datetime.utcnow()` deprecated in Python 3.12

You're on 3.12. This throws `DeprecationWarning` on every tracker call.

```python
# tracker.py — replace this
datetime.datetime.utcnow().isoformat() + "Z"

# with this
datetime.datetime.now(datetime.UTC).isoformat() + "Z"
```

---

### 2. `estimate_tokens` returns 1 for empty strings

`max(1, 0 // 4)` = 1, so empty output is counted as 1 token saved, inflating your stats.

```python
# core/utils.py
def estimate_tokens(text: str) -> int:
    return len(text) // 4   # 0 for empty, no floor
```

---

### 3. `_filter_simple` doesn't catch rejected pushes

You check `if "error" in raw.lower()` but a rejected push says `"rejected"` or `"denied"`, not `"error"`. This would return `"ok main"` for a failed push.

```python
def _filter_simple(raw: str, sub: str) -> str:
    if any(w in raw.lower() for w in ("error", "rejected", "denied", "fatal")):
        return raw[:300]
    ...
```

---

### 4. `_filter_log` matches verbose log header lines

`l.startswith("commit ")` catches the full verbose format header (`commit <full-hash>`) which is noise. Restrict to short-hash lines only:

```python
def _filter_log(raw: str) -> str:
    lines = [l for l in raw.splitlines() if re.match(r'^[0-9a-f]{7,}\s', l)]
    return "\n".join(lines[:10]) if lines else raw[:200]
```

---

### 5. `structure_only` has no recursion depth limit

Deeply nested JSON will hit Python's default recursion limit (1000) and throw `RecursionError`.

```python
# core/filter.py
def convert(val, depth=0):
    if depth > 10:
        return "..."
    if isinstance(val, dict):
        return {k: convert(v, depth + 1) for k, v in val.items()}
    elif isinstance(val, list):
        return [convert(val[0], depth + 1)] if val else []
    else:
        return type(val).__name__
```

---

## Security / Privacy

### 6. Full command strings logged to MemCore

If `agy` runs `curl -H "Authorization: Bearer sk-..."` or `git clone https://user:pass@repo`, the full string ends up in MemCore. Add a scrubber before building the payload:

```python
# tracker.py
import re
_SECRET_RE = re.compile(r'(bearer|token|password|secret|key|auth)\s+\S+', re.I)

def _scrub(cmd: str) -> str:
    return _SECRET_RE.sub(r'\1 [REDACTED]', cmd)

# then in track():
"command": _scrub(original_cmd),
```

---

### 7. No validation on `cwd` parameter in MCP tool

Anything calling the MCP server could pass `cwd="/etc"` or `cwd="C:\\Windows\\System32"`. Add a basic guard:

```python
# mcp_server.py — top of rtk_run_command
resolved = Path(cwd).resolve()
if not resolved.exists():
    return f"Error: cwd does not exist: {cwd}"
if not resolved.is_dir():
    return f"Error: cwd is not a directory: {cwd}"
```

---

## Reliability

### 8. No error handling around filter functions in MCP server

If `_filter_status` throws on unexpected output, the whole `rtk_run_command` call crashes and `agy` gets nothing. Wrap every filter call:

```python
# mcp_server.py
try:
    filtered = _filter_status(raw)
except Exception as e:
    logging.warning(f"filter failed for {main_cmd}: {e}")
    filtered = raw  # fall back to unfiltered
```

---

### 9. Tracker HTTP call blocks the response

Every command waits for the MemCore POST to complete before returning filtered output to the agent. Fire and forget with a daemon thread:

```python
# tracker.py
import threading

def _post(payload: dict, port: str):
    try:
        requests.post(f"http://localhost:{port}/agentmemory/command/log", json=payload, timeout=2)
    except Exception:
        pass

def track(...):
    ...
    threading.Thread(target=_post, args=(payload, port), daemon=True).start()
```

---

### 10. `_filter_ps` breaks on container names with spaces

`re.split(r'\s{2,}', line.strip())` relies on consistent column spacing which breaks on longer names. Use `--format` instead for reliable parsing:

```python
# docker_cmd.py
def run(args: list[str], verbose: bool = False):
    sub = args[0] if args else ""
    if sub == "ps":
        fmt_cmd = ["docker", "ps", "--format",
                   "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"]
        stdout, stderr, code = execute_command(fmt_cmd)
        print(stdout.strip())
    ...
```

---

## Dead Code

### 11. `dual_mode_parse` is never called

Defined in `filter.py`, referenced nowhere. Either wire it into `docker_cmd.py` or future modules, or delete it. Dead code is noise when `agy` reads your source.

---

## Developer Experience

### 12. `[project.scripts]` missing from `pyproject.toml`

You can't install as a CLI tool with `uv tool install .` without it:

```toml
[project.scripts]
pyrtk = "main:app"
rtk-mcp = "mcp_server:mcp.run"
```

---

### 13. `verbose` flag ignored in all modules except `git.py`

Every command accepts it as a parameter but only `git.py` uses it. Either wire it consistently or remove it from the other signatures so it's not misleading.

```python
# consistent pattern for each module
if verbose:
    print(f"[pyrtk] {main_cmd} → {len(filtered)}/{len(raw)} chars "
          f"({100 - len(filtered)*100//max(len(raw),1)}% saved)", file=sys.stderr)
```

---

### 14. No logging

When the MCP server silently fails (bad import, MemCore down, filter crash), you have zero visibility. Add a minimal file logger:

```python
# mcp_server.py or a shared config
import logging
from pathlib import Path

log_path = Path.home() / ".local/share/pyrtk/pyrtk.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=log_path,
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s"
)
```

---

### 15. `AGENTS.md` and `antigravity-rtk-rules.md` are empty

Without these, `agy` doesn't know the MCP tool exists. Minimum content:

```markdown
# pyrtk MCP Tool

When running shell commands, ALWAYS use the `rtk_run_command` MCP tool
instead of running them directly. It compresses output before it enters
context, saving 60-90% of tokens on common dev commands.

## Usage

- `rtk_run_command("git status")`
- `rtk_run_command("pytest", cwd="/path/to/project")`
- `rtk_run_command("docker ps")`
- `rtk_run_command("ls .", cwd="/path/to/dir")`

## Supported commands with smart filtering

git, pytest, docker ps/logs, ls

## Unsupported commands

Pass through `rtk_run_command` anyway — it will return raw output
and still log the token usage to MemCore.
```

---

### 16. No `--version` command and no `rtk_gain` MCP tool

`pyrtk --version` is a one-liner with typer. More impactful: expose `gain` as an MCP tool so `agy` can check savings without you switching to CLI:

```python
# mcp_server.py
@mcp.tool()
def rtk_gain() -> str:
    """Return token savings summary from MemCore."""
    port = os.getenv("MEMCORE_PORT", "3111")
    try:
        res = requests.get(f"http://localhost:{port}/agentmemory/gain", timeout=3)
        if res.status_code == 200:
            d = res.json()
            return (f"Commands: {d.get('total_commands', 0)} | "
                    f"Saved: {d.get('total_saved_t', 0):,} tokens | "
                    f"Avg: {d.get('avg_pct', 0):.1f}%")
    except Exception as e:
        return f"MemCore unreachable: {e}"
```

---

## Testing

### 17. `test_mcp.py` imports the function directly

It bypasses the MCP protocol entirely — won't catch registration issues, schema problems, or tool-call format errors. A real smoke test would use the MCP client:

```python
# test_mcp.py
from mcp import Client
import asyncio

async def test_rtk_run():
    async with Client("pyrtk") as client:
        result = await client.call_tool("rtk_run_command", {"command": "git status"})
        assert result is not None

asyncio.run(test_rtk_run())
```

---

### 18. Zero unit tests for filter functions

The filters are the most testable and most likely to break on edge cases. Minimum coverage:

```python
# tests/test_filters.py
from src.pyrtk.core.filter import dedup, structure_only
from src.pyrtk.cmds.git import _filter_status, _filter_simple

def test_dedup_consecutive():
    assert dedup("a\na\na\nb") == "a (×3)\nb"

def test_dedup_no_repeats():
    assert dedup("a\nb\nc") == "a\nb\nc"

def test_filter_status_clean():
    assert _filter_status("") == "clean"

def test_filter_status_modified():
    result = _filter_status(" M src/main.py\n?? new_file.py")
    assert "M src/main.py" in result
    assert "untracked: 1" in result

def test_structure_only_flat():
    assert '"int"' in structure_only('{"count": 42}')

def test_structure_only_nested():
    out = structure_only('{"user": {"id": 1, "name": "alice"}}')
    assert '"int"' in out and '"str"' in out

def test_filter_simple_rejected_push():
    raw = "error: failed to push some refs\nTo origin\n! [rejected] main -> main"
    assert "rejected" in _filter_simple(raw, "push").lower()
```

---

### 19. No test for MemCore-down fallback behavior

The tracker and `report()` silently swallow connection errors, which is correct — but it's untested. At minimum verify it doesn't raise:

```python
def test_track_memcore_down(monkeypatch):
    monkeypatch.setenv("MEMCORE_PORT", "9")  # nothing running on port 9
    from src.pyrtk.tracker import track
    track("git status", "pyrtk git status", "raw", "filtered", 10)  # should not raise
```

---

## Architecture

### 20. Root `mcp_server.py` uses fragile absolute imports

`from src.pyrtk...` only works if the process starts from exactly the `rtk/` directory. If `agy` spawns the server from a different cwd, it breaks. Fix by installing as a package with `uv` and using installed package imports, or add a `sys.path` guard at the top of the root entrypoint:

```python
# mcp_server.py (root)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.pyrtk.mcp_server import mcp
if __name__ == "__main__":
    mcp.run()
```

---

### 21. `pytest_cmd.py` failure line cap is hardcoded

50 lines is arbitrary. Make it configurable:

```python
# pytest_cmd.py
MAX_FAILURE_LINES = int(os.getenv("RTK_MAX_FAILURE_LINES", "50"))

# ...
return "\n".join(failures[:MAX_FAILURE_LINES])
```

---

### 22. No passthrough mode

No way to run a command completely unfiltered when needed — useful for debugging or when a filter is too aggressive. Add a generic passthrough tool to the MCP server:

```python
# mcp_server.py
@mcp.tool()
def rtk_passthrough(command: str, cwd: str = ".") -> str:
    """Run a command with zero filtering. Use when you need full raw output."""
    args = shlex.split(command)
    stdout, stderr, code = execute_command(args, cwd=cwd)
    return stdout + stderr
```

---

## Implementation Specifications

Full implementation specs for everything needed to reach RTK parity. Build in dependency order: `core/filter.py` → command modules → `main.py` → MCP servers → `AGENTS.md`.

---

### A. `src/pyrtk/core/filter.py` — Additions

Add `FilterLevel`, `code_filter`, and all language compression helpers. Append after existing `dual_mode_parse`. Also fix `structure_only` null bug here.

```python
# --- PATCH: fix structure_only NoneType bug ---
def structure_only(json_str: str) -> str:
    try:
        data = json.loads(json_str)
        def convert(val, depth: int = 0):
            if depth > 10:
                return "..."
            if val is None:                          # ← fix: was type(None).__name__
                return "null"
            if isinstance(val, dict):
                return {k: convert(v, depth + 1) for k, v in val.items()}
            elif isinstance(val, list):
                return [convert(val[0], depth + 1)] if val else []
            else:
                return type(val).__name__
        return json.dumps(convert(data), indent=2)
    except json.JSONDecodeError:
        return json_str


# --- NEW: code_filter for read_cmd ---

from enum import Enum

_BLANK_LINES_RE = re.compile(r'\n{3,}')
_C_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)

class FilterLevel(Enum):
    NONE = "none"
    MINIMAL = "minimal"        # strip comments + collapse blanks (~20-40%)
    AGGRESSIVE = "aggressive"  # strip function bodies, keep signatures (~60-90%)


_LANGUAGE_LINE_COMMENT: dict[str, str] = {
    "python": "#", "ruby": "#",
    "javascript": "//", "typescript": "//",
    "go": "//", "rust": "//", "java": "//",
    "csharp": "//", "c": "//", "kotlin": "//",
}


def code_filter(content: str, language: str, level: FilterLevel = FilterLevel.MINIMAL) -> str:
    """Language-aware source code compression.

    Args:
        content:  Raw file text.
        language: Language key from LANGUAGE_MAP in read_cmd.py.
        level:    Compression level.

    Returns:
        Compressed text, or original if language is unsupported.
    """
    if level == FilterLevel.NONE or language == "unknown":
        return content
    if level == FilterLevel.MINIMAL:
        return _minimal_filter(content, language)
    if level == FilterLevel.AGGRESSIVE:
        return _aggressive_filter(content, language)
    return content


def _minimal_filter(content: str, language: str) -> str:
    """Strip comments and collapse 3+ blank lines into one."""
    line_prefix = _LANGUAGE_LINE_COMMENT.get(language)
    if not line_prefix:
        return content

    # Strip C-style block comments for C-family languages
    if language not in ("python", "ruby"):
        content = _C_BLOCK_COMMENT_RE.sub("", content)
    elif language == "ruby":
        content = re.sub(r"^=begin.*?^=end", "", content, flags=re.MULTILINE | re.DOTALL)

    result = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(line_prefix):
            continue
        result.append(line)

    joined = "\n".join(result)
    return _BLANK_LINES_RE.sub("\n\n", joined).strip()


def _aggressive_filter(content: str, language: str) -> str:
    """Minimal-filter first, then strip function bodies."""
    content = _minimal_filter(content, language)
    if language == "python":
        return _aggressive_python(content)
    if language in ("javascript", "typescript", "go", "rust", "java", "csharp", "c", "kotlin"):
        return _aggressive_brace(content)
    return content  # unsupported — return minimal-filtered


def _aggressive_python(content: str) -> str:
    """Python: keep imports, decorators, class/def signatures + docstrings. Drop bodies."""
    lines = content.splitlines()
    result: list[str] = []
    skip_until_indent: int | None = None
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip()) if stripped else 999

        # Resume from skip when we dedent back to signature level
        if skip_until_indent is not None:
            if stripped and indent <= skip_until_indent:
                skip_until_indent = None
            else:
                i += 1
                continue

        is_sig = stripped.startswith(("def ", "async def ", "class "))
        is_keep = (
            not stripped
            or stripped.startswith(("import ", "from ", "@", "__all__", "__version__", "__slots__"))
            or is_sig
        )

        if is_keep:
            result.append(line)

            if is_sig:
                # Look ahead for docstring
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and lines[j].strip().startswith(('"""', "'''")):
                    quote = lines[j].strip()[:3]
                    result.append(lines[j])
                    if lines[j].count(quote) < 2:  # multi-line docstring
                        j += 1
                        while j < len(lines):
                            result.append(lines[j])
                            if quote in lines[j].strip():
                                j += 1
                                break
                            j += 1
                    else:
                        j += 1
                    i = j

                # Add ellipsis body placeholder and start skipping
                sig_indent = indent
                body_indent = " " * (sig_indent + 4)
                result.append(f"{body_indent}...")
                skip_until_indent = sig_indent
                continue

        elif indent == 0 and stripped and "=" in stripped:
            # Keep module-level assignments (constants, __all__, etc.)
            result.append(line)

        i += 1

    return "\n".join(result)


def _aggressive_brace(content: str) -> str:
    """Brace-delimited languages: keep signatures, replace bodies with { ... }."""
    _SIG_RE = re.compile(
        r"\b(public|private|protected|internal|static|async|"
        r"func|fn|fun|void|int|string|bool|"
        r"class|struct|interface|impl|enum|type)\b"
    )

    lines = content.splitlines()
    result: list[str] = []
    brace_depth = 0
    body_start_depth: int | None = None

    for line in lines:
        stripped = line.strip()
        open_b = line.count("{")
        close_b = line.count("}")
        is_sig = bool(_SIG_RE.search(stripped))
        is_structural = stripped.startswith(("import ", "using ", "package ", "#include", "//"))

        if body_start_depth is None:
            result.append(line)
            if (is_sig or is_structural) and open_b > close_b:
                body_start_depth = brace_depth
                result.append("  ...")
        else:
            brace_depth += open_b - close_b
            if brace_depth <= body_start_depth:
                result.append(line)
                body_start_depth = None

        brace_depth += open_b - close_b

    return "\n".join(result)
```

---

### B. `src/pyrtk/cmds/ruff_cmd.py` — New File

RTK equivalent: `rtk lint`. Expected savings: **80–95%**.

```python
# src/pyrtk/cmds/ruff_cmd.py
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

logger = logging.getLogger(__name__)

_MAX_VIOLATIONS = int(os.getenv("RTK_MAX_VIOLATIONS", "20"))
_MAX_PER_RULE = int(os.getenv("RTK_MAX_PER_RULE", "3"))


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy ruff — violations grouped by rule code via JSON output.

    Subcommands handled: check (default), format.
    Falls back to text parsing if JSON mode fails.
    """
    sub = args[0] if args else "check"
    cmd = ["ruff"] + args

    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)

    if sub == "check":
        filtered = _filter_check_json(args) or _filter_check_text(raw)
    elif sub == "format":
        filtered = _filter_format(raw)
    else:
        filtered = raw

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] ruff {sub} → {pct}% saved", flush=True)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_check_json(args: list[str]) -> str | None:
    """Re-run ruff check with --output-format json for reliable structured parsing."""
    clean_args = [a for a in args[1:] if not a.startswith("--output-format")]
    json_cmd = ["ruff", "check", "--output-format", "json"] + clean_args

    stdout, _, _ = execute_command(json_cmd)

    try:
        violations: list[dict] = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning("ruff JSON parse failed — falling back to text: %s", stdout[:80])
        return None

    if not violations:
        return "ruff: no violations ✓"

    # Group by rule code, sorted by frequency descending
    by_rule: dict[str, list[str]] = defaultdict(list)
    for v in violations:
        rule = v.get("code") or "?"
        filename = v.get("filename", "?")
        row = v.get("location", {}).get("row", "?")
        msg = v.get("message", "")
        by_rule[rule].append(f"  {filename}:{row} {msg}")

    total = len(violations)
    lines = [f"ruff: {total} violation(s) — {len(by_rule)} rule(s)\n"]
    shown = 0

    for rule, instances in sorted(by_rule.items(), key=lambda x: -len(x[1])):
        lines.append(f"{rule} ({len(instances)}×)")
        for inst in instances[:_MAX_PER_RULE]:
            lines.append(inst)
            shown += 1
        if len(instances) > _MAX_PER_RULE:
            lines.append(f"  ... +{len(instances) - _MAX_PER_RULE} more")
        if shown >= _MAX_VIOLATIONS:
            remaining = total - shown
            if remaining > 0:
                lines.append(f"\n[{remaining} violations omitted — run ruff check directly]")
            break

    return "\n".join(lines)


def _filter_check_text(raw: str) -> str:
    """Fallback text parser — group violations by file."""
    _LINE_RE = re.compile(r"^(.+?):(\d+):\d+:\s+([A-Z]\d+)\s+(.+)$")
    by_file: dict[str, int] = defaultdict(int)

    for line in raw.splitlines():
        m = _LINE_RE.match(line)
        if m:
            by_file[m.group(1)] += 1

    if not by_file:
        return raw[:400] if raw.strip() else "ruff: no violations ✓"

    total = sum(by_file.values())
    result = [f"ruff: {total} violation(s) across {len(by_file)} file(s)"]
    for f, count in sorted(by_file.items(), key=lambda x: -x[1])[:15]:
        result.append(f"  {f}: {count}")
    return "\n".join(result)


def _filter_format(raw: str) -> str:
    """Extract summary line from ruff format output."""
    for line in raw.splitlines():
        s = line.strip()
        if s and any(w in s for w in ("reformatted", "unchanged", "file", "error")):
            return s
    return raw[:200]
```

---

### C. `src/pyrtk/cmds/grep_cmd.py` — New File

RTK equivalent: `rtk grep`. Expected savings: **70–85%**.

```python
# src/pyrtk/cmds/grep_cmd.py
from __future__ import annotations

import os
import re
import shutil
import time
from collections import defaultdict

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_FILES = int(os.getenv("RTK_GREP_MAX_FILES", "15"))
_PREVIEW_LEN = int(os.getenv("RTK_GREP_PREVIEW_LEN", "80"))

# grep -n / rg format: filename:lineno:content
_GREP_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$")


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy grep/rg — group matches by file with counts and one preview per file.

    Auto-selects rg over grep when available.
    Exit code 1 (no matches) is not treated as an error.
    """
    tool = "rg" if shutil.which("rg") else "grep"
    cmd = [tool] + args

    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_grep(raw)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] {tool} → {pct}% saved", flush=True)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    # Exit 1 from grep/rg means "no matches" — not a failure worth propagating
    if code not in (0, 1):
        raise SystemExit(code)


def _filter_grep(raw: str) -> str:
    """Group grep output by file. Shows match count + first preview per file."""
    if not raw.strip():
        return "no matches"

    by_file: dict[str, list[str]] = defaultdict(list)
    unmatched: list[str] = []

    for line in raw.splitlines():
        m = _GREP_LINE_RE.match(line)
        if m:
            filename, _, content = m.groups()
            by_file[filename].append(content.strip()[:_PREVIEW_LEN])
        else:
            unmatched.append(line)

    # Single-file mode (no filename prefix)
    if not by_file and unmatched:
        total = len(unmatched)
        result = [f"{total} match(es)"]
        for line in unmatched[:5]:
            result.append(f"  {line}")
        if total > 5:
            result.append(f"  ... +{total - 5} more")
        return "\n".join(result)

    total_matches = sum(len(v) for v in by_file.values())
    result = [f"{total_matches} match(es) in {len(by_file)} file(s)"]

    for filename, matches in sorted(by_file.items(), key=lambda x: -len(x[1]))[:_MAX_FILES]:
        preview = matches[0] if matches else ""
        result.append(f"  {filename}: {len(matches)} — {preview}")

    if len(by_file) > _MAX_FILES:
        result.append(f"  ... +{len(by_file) - _MAX_FILES} more file(s)")

    return "\n".join(result)
```

---

### D. `src/pyrtk/cmds/find_cmd.py` — New File

RTK equivalent: `rtk find`. Expected savings: **60–75%**.

```python
# src/pyrtk/cmds/find_cmd.py
from __future__ import annotations

import os
import time
from collections import defaultdict
from pathlib import Path

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_DIRS = int(os.getenv("RTK_FIND_MAX_DIRS", "20"))
_RAW_THRESHOLD = int(os.getenv("RTK_FIND_RAW_THRESHOLD", "5"))


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy find — collapse flat path list into a directory summary with counts."""
    cmd = ["find"] + args

    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_find(raw)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] find → {pct}% saved", flush=True)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_find(raw: str) -> str:
    """Collapse flat find output into directory tree with file counts."""
    paths = [line.strip() for line in raw.splitlines() if line.strip()]

    if not paths:
        return "no results"

    # Small result — return as-is
    if len(paths) <= _RAW_THRESHOLD:
        return "\n".join(paths)

    # Group by parent directory
    by_dir: dict[str, int] = defaultdict(int)
    for p in paths:
        parent = str(Path(p).parent)
        by_dir[parent] += 1

    total = len(paths)
    result = [f"{total} result(s) across {len(by_dir)} director(ies)"]

    for directory, count in sorted(by_dir.items(), key=lambda x: -x[1])[:_MAX_DIRS]:
        result.append(f"  {directory}: {count} file(s)")

    if len(by_dir) > _MAX_DIRS:
        result.append(f"  ... +{len(by_dir) - _MAX_DIRS} more directories")

    return "\n".join(result)
```

---

### E. `src/pyrtk/cmds/pip_cmd.py` — New File

RTK equivalent: `rtk pip`. Expected savings: **70–80%**. Auto-detects `uv`.

```python
# src/pyrtk/cmds/pip_cmd.py
from __future__ import annotations

import json
import shutil
import time

from ..core.utils import execute_command
from ..tracker import track

# Fields to keep from `pip show` output
_SHOW_KEEP = {"Name", "Version", "Summary", "Requires", "Required-by", "Location"}


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy pip/uv pip — compact JSON list, trimmed show output.

    Prefers uv when available. Handles list and show subcommands.
    """
    tool = "uv" if shutil.which("uv") else "pip"
    sub = args[0] if args else "list"

    if sub == "list":
        cmd = ([tool, "pip", "list", "--format", "json"]
               if tool == "uv"
               else ["pip", "list", "--format", "json"])
        t0 = time.time()
        stdout, stderr, code = execute_command(cmd)
        exec_ms = int((time.time() - t0) * 1000)
        raw = stdout + stderr
        filtered = _filter_list(raw)

    elif sub == "show":
        cmd = ([tool, "pip", "show"] + args[1:]
               if tool == "uv"
               else ["pip", "show"] + args[1:])
        t0 = time.time()
        stdout, stderr, code = execute_command(cmd)
        exec_ms = int((time.time() - t0) * 1000)
        raw = stdout + stderr
        filtered = _filter_show(raw)

    else:
        cmd = ([tool, "pip"] + args if tool == "uv" else ["pip"] + args)
        t0 = time.time()
        stdout, stderr, code = execute_command(cmd)
        exec_ms = int((time.time() - t0) * 1000)
        raw = stdout + stderr
        filtered = raw

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] pip {sub} → {pct}% saved", flush=True)

    print(filtered)
    track(" ".join(cmd), f"pyrtk pip {sub}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_list(raw: str) -> str:
    """Parse JSON package list into compact two-column table."""
    try:
        packages: list[dict] = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:400]

    if not packages:
        return "no packages installed"

    lines = [f"{len(packages)} package(s) installed\n"]
    for pkg in sorted(packages, key=lambda x: x.get("name", "").lower()):
        name = pkg.get("name", "?")
        version = pkg.get("version", "?")
        lines.append(f"  {name:<30} {version}")

    return "\n".join(lines)


def _filter_show(raw: str) -> str:
    """Keep only the most relevant fields from pip show output."""
    result = []
    for line in raw.splitlines():
        if ":" in line:
            key = line.split(":", 1)[0].strip()
            if key in _SHOW_KEEP:
                result.append(line)
    return "\n".join(result) if result else raw[:300]
```

---

### F. `src/pyrtk/cmds/read_cmd.py` — New File

RTK equivalent: `rtk read` / `rtk smart`. Expected savings: **20–90%** depending on level.

```python
# src/pyrtk/cmds/read_cmd.py
from __future__ import annotations

import os
import time
from pathlib import Path

from ..core.filter import FilterLevel, code_filter
from ..core.utils import estimate_tokens
from ..tracker import track

_DEFAULT_LEVEL = os.getenv("RTK_READ_LEVEL", "minimal")
_MAX_CHARS = int(os.getenv("RTK_READ_MAX_CHARS", "50000"))

# Extension → language key for code_filter
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".c": "c", ".cpp": "c", ".cc": "c",
    ".h": "c", ".hpp": "c",
    ".rb": "ruby",
    ".kt": "kotlin",
}


def run(args: list[str], verbose: bool = False) -> None:
    """Read a source file with language-aware compression.

    Usage:
        pyrtk read <file>                    # minimal compression
        pyrtk read <file> aggressive         # strip function bodies
        pyrtk read <file> --level none       # passthrough (no compression)

    Environment:
        RTK_READ_LEVEL   default level (none|minimal|aggressive), default: minimal
        RTK_READ_MAX_CHARS  truncation threshold, default: 50000
    """
    if not args:
        print("Usage: pyrtk read <file> [none|minimal|aggressive]")
        raise SystemExit(1)

    filepath = args[0]

    # Parse optional level from remaining args
    level_str = _DEFAULT_LEVEL
    for a in args[1:]:
        if a in ("none", "minimal", "aggressive"):
            level_str = a
        elif a == "--level" and args.index(a) + 1 < len(args):
            level_str = args[args.index(a) + 1]

    try:
        level = FilterLevel(level_str)
    except ValueError:
        level = FilterLevel.MINIMAL

    path = Path(filepath)

    if not path.exists():
        print(f"Error: file not found: {filepath}")
        raise SystemExit(1)
    if not path.is_file():
        print(f"Error: not a file: {filepath}")
        raise SystemExit(1)

    t0 = time.time()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        print(f"Error: permission denied: {filepath}")
        raise SystemExit(1)
    exec_ms = int((time.time() - t0) * 1000)

    # Truncate before filtering — avoids O(n²) on huge generated files
    was_truncated = False
    if len(raw) > _MAX_CHARS:
        raw = raw[:_MAX_CHARS]
        was_truncated = True

    language = LANGUAGE_MAP.get(path.suffix.lower(), "unknown")
    filtered = code_filter(raw, language, level)

    if was_truncated:
        filtered += f"\n\n[... file truncated at {_MAX_CHARS} chars]"

    if verbose:
        in_tok = estimate_tokens(raw)
        out_tok = estimate_tokens(filtered)
        pct = int(max(0, in_tok - out_tok) / max(in_tok, 1) * 100)
        print(
            f"[pyrtk] read {path.name} ({language}, {level.value}) "
            f"→ {in_tok}→{out_tok} tokens, {pct}% saved",
            flush=True,
        )

    print(filtered)
    track(
        f"read {filepath}",
        f"pyrtk read {filepath} --level {level.value}",
        raw,
        filtered,
        exec_ms,
    )
```

---

### G. `src/pyrtk/cmds/err_cmd.py` — New File

RTK equivalent: `rtk err`. Expected savings: **varies** (50–95% on noisy tools).

```python
# src/pyrtk/cmds/err_cmd.py
from __future__ import annotations

import re
import time

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_OUTPUT_LINES = 60

_ERROR_RE = re.compile(
    r"(error|exception|traceback|fatal|critical|failed|failure|"
    r"panic|abort|denied|rejected|not found|cannot|could not|unable to)",
    re.IGNORECASE,
)


def run(args: list[str], verbose: bool = False) -> None:
    """Generic wrapper — return only stderr and error-pattern lines from stdout.

    Usage: pyrtk err <any command> [args...]

    Use this for commands not yet covered by dedicated modules. It will
    always surface errors even if they're buried in verbose output.
    """
    if not args:
        print("Usage: pyrtk err <command> [args...]")
        raise SystemExit(1)

    t0 = time.time()
    stdout, stderr, code = execute_command(args)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_errors(stdout, stderr)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] err → {pct}% saved (exit: {code})", flush=True)

    if filtered.strip():
        print(filtered)
    elif code != 0:
        print(f"exit {code} (no error output captured — run command directly for full output)")
    else:
        print("ok")

    track(" ".join(args), f"pyrtk err {' '.join(args)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_errors(stdout: str, stderr: str) -> str:
    """Return stderr lines first, then error-pattern stdout lines. Deduplicated."""
    result: list[str] = []

    # stderr always included
    for line in stderr.splitlines():
        if line.strip():
            result.append(line)

    # stdout — error-pattern lines only
    for line in stdout.splitlines():
        if _ERROR_RE.search(line):
            result.append(line)

    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for line in result:
        key = line.strip()
        if key not in seen:
            seen.add(key)
            deduped.append(line)

    return "\n".join(deduped[:_MAX_OUTPUT_LINES])
```

---

### H. `src/pyrtk/cmds/test_cmd.py` — New File

RTK equivalent: `rtk test`. Expected savings: **85–99%**. Handles pytest, Jest, Go test, Mocha, RSpec, any xUnit-style runner.

```python
# src/pyrtk/cmds/test_cmd.py
from __future__ import annotations

import os
import re
import time

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

_MAX_FAILURE_LINES = int(os.getenv("RTK_MAX_FAILURE_LINES", "80"))

# Patterns that mark the start of a failure block across runners
_FAILURE_START_RE = re.compile(
    r"(=+\s*(FAILURES|ERRORS|FAILED TESTS|Error Summary)\s*=+|"  # pytest
    r"● .+|"                    # Jest
    r"FAIL .+\.(?:js|ts|jsx|tsx)|"  # Jest file-level
    r"^\s+\d+\) .+|"           # Mocha numbered failure
    r"Failures:\s*$|"          # RSpec
    r"--- FAIL:|"              # Go test
    r"FAILED\s+\w)",           # Generic
    re.IGNORECASE | re.MULTILINE,
)

# Summary line patterns (used to extract the final verdict)
_SUMMARY_RE = re.compile(
    r"(\d+\s+(passed|failed|pending|skipped|error|flaky)|"
    r"\d+\s+examples?,\s*\d+\s+failure|"   # RSpec
    r"Tests run:\s*\d+|"                   # JUnit
    r"^ok\s+\S+\s+[\d.]+s$|"             # Go
    r"Test Suites?:.*\n.*Tests?:)",        # Jest
    re.IGNORECASE | re.MULTILINE,
)

_COLLECTION_ERROR_RE = re.compile(
    r"(no tests? (ran|collected|found)|collected 0 items|import error|syntaxerror)",
    re.IGNORECASE,
)


def run(args: list[str], verbose: bool = False) -> None:
    """Generic test runner wrapper — show failures only.

    Usage: pyrtk test <command> [args...]
    Example: pyrtk test go test ./...
             pyrtk test npx jest --ci

    Works with: pytest, Jest, Mocha, Go test, RSpec, dotnet test, cargo test.
    Falls back to last 20 lines on unrecognised format.
    """
    if not args:
        print("Usage: pyrtk test <command> [args...]")
        raise SystemExit(1)

    t0 = time.time()
    stdout, stderr, code = execute_command(args)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = _filter_test_output(raw, code)

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] test → {pct}% saved (exit: {code})", flush=True)

    print(filtered)
    track(" ".join(args), f"pyrtk test {' '.join(args)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_test_output(raw: str, exit_code: int) -> str:
    """Extract failure block + summary from any test runner output."""
    lines = raw.splitlines()

    # Detect collection errors before anything else
    if _COLLECTION_ERROR_RE.search(raw):
        # Return the relevant section — don't say "all passed"
        relevant = [l for l in lines if l.strip() and not l.strip().startswith("=")]
        return "\n".join(relevant[:20]) or f"Collection error (exit {exit_code})"

    # Extract summary lines
    summary_matches = list(_SUMMARY_RE.finditer(raw))
    summary_line = summary_matches[-1].group(0).strip() if summary_matches else ""

    # Extract failure block
    failures: list[str] = []
    in_failure = False

    for line in lines:
        if _FAILURE_START_RE.search(line):
            in_failure = True

        if in_failure:
            failures.append(line)

        # Stop at summary (but only after we've captured some failures)
        if in_failure and len(failures) > 3 and _SUMMARY_RE.search(line):
            break

    if not failures:
        if exit_code == 0:
            return summary_line or "all tests passed"
        # Non-zero exit but no structured failures — tail of output
        tail = lines[-20:] if len(lines) > 20 else lines
        return "\n".join(tail) or f"tests failed (exit {exit_code})"

    result = failures[:_MAX_FAILURE_LINES]
    if summary_line and summary_line not in result[-1]:
        result.append(summary_line)

    if len(failures) > _MAX_FAILURE_LINES:
        result.append(f"[{len(failures) - _MAX_FAILURE_LINES} lines omitted — run directly for full output]")

    return "\n".join(result)
```

---

### I. `main.py` — Updated Full File

Wire all new modules and commands. Replace entirely.

```python
# main.py
from __future__ import annotations

import sys

import typer

from src.pyrtk import cmds
from src.pyrtk.tracker import report

app = typer.Typer(
    help="pyrtk — local RTK-equivalent, Python edition",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)

_CTX = {"ignore_unknown_options": True, "allow_extra_args": True}

# ── Existing commands ──────────────────────────────────────────────────────────

@app.command(context_settings=_CTX)
def git(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Proxy git — compact status, log, diff, push output."""
    cmds.git.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def pytest(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Proxy pytest — failures only."""
    cmds.pytest_cmd.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def ls(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Compress directory listing into tree structure."""
    cmds.ls_cmd.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def docker(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Proxy docker ps/logs with dedup and compact table."""
    cmds.docker_cmd.run(ctx.args, verbose)


# ── New commands ───────────────────────────────────────────────────────────────

@app.command(context_settings=_CTX)
def ruff(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Proxy ruff — violations grouped by rule code via JSON output."""
    cmds.ruff_cmd.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def grep(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Proxy grep/rg — group matches by file with counts."""
    cmds.grep_cmd.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def find(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Proxy find — collapse results to directory summary."""
    cmds.find_cmd.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def pip(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Proxy pip/uv pip list — compact package table."""
    cmds.pip_cmd.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def read(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Read a source file with language-aware compression.

    Levels: none | minimal (default) | aggressive
    Example: pyrtk read src/main.py aggressive
    """
    cmds.read_cmd.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def err(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Run any command — return stderr and error-pattern lines only.

    Example: pyrtk err cargo build
    """
    cmds.err_cmd.run(ctx.args, verbose)


@app.command(context_settings=_CTX)
def test(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")) -> None:
    """Run any test command — failures only. Works with pytest, Jest, Go test, RSpec.

    Example: pyrtk test go test ./...
    """
    cmds.test_cmd.run(ctx.args, verbose)


# ── Utility commands ───────────────────────────────────────────────────────────

@app.command()
def gain() -> None:
    """Show token savings report from MemCore."""
    report()


@app.command()
def dedup(file: str = typer.Argument(None)) -> None:
    """Deduplicate consecutive lines from a file or stdin."""
    from src.pyrtk.core.filter import dedup as run_dedup

    try:
        content = (
            open(file, encoding="utf-8").read()  # noqa: WPS515
            if file
            else sys.stdin.read()
        )
    except FileNotFoundError:
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(1)
    print(run_dedup(content))


@app.command()
def structure(file: str = typer.Argument(None)) -> None:
    """Extract structural schema from a JSON file or stdin."""
    from src.pyrtk.core.filter import structure_only

    try:
        content = (
            open(file, encoding="utf-8").read()  # noqa: WPS515
            if file
            else sys.stdin.read()
        )
    except FileNotFoundError:
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(1)
    print(structure_only(content))


@app.command()
def version() -> None:
    """Show pyrtk version."""
    typer.echo("pyrtk 0.2.0")


if __name__ == "__main__":
    app()
```

---

### J. `mcp_server.py` (root) — Updated Full File

Add routing for all new commands + three new MCP tools. Replace entirely.

```python
# mcp_server.py
# ponytail: root entrypoint avoids sys.path/relative import hacks in MCP spawn context
from __future__ import annotations

import datetime
import logging
import os
import shlex
import threading
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

from src.pyrtk.core.filter import FilterLevel, code_filter
from src.pyrtk.core.utils import execute_command, estimate_tokens, strip_ansi
from src.pyrtk.cmds.git import _filter_status, _filter_log, _filter_diff, _filter_simple
from src.pyrtk.cmds.pytest_cmd import _filter_pytest
from src.pyrtk.cmds.docker_cmd import _filter_ps
from src.pyrtk.cmds.ruff_cmd import _filter_check_json, _filter_check_text, _filter_format as _ruff_format
from src.pyrtk.cmds.grep_cmd import _filter_grep
from src.pyrtk.cmds.find_cmd import _filter_find
from src.pyrtk.cmds.pip_cmd import _filter_list as _pip_list, _filter_show as _pip_show
from src.pyrtk.cmds.err_cmd import _filter_errors
from src.pyrtk.cmds.test_cmd import _filter_test_output
from src.pyrtk.core.filter import dedup

log_path = Path.home() / ".local" / "share" / "pyrtk" / "pyrtk.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(log_path),
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("pyrtk")

_MEMCORE_PORT = os.getenv("MEMCORE_PORT", "3111")

# ── Internal helpers ───────────────────────────────────────────────────────────

_SECRET_RE = import re; re.compile(
    r"(bearer|authorization|token|password|secret|key|auth)\s+\S+",
    re.IGNORECASE,
)

def _scrub(cmd: str) -> str:
    """Remove credential-like strings before logging to MemCore."""
    return _SECRET_RE.sub(r"\1 [REDACTED]", cmd)


def _post_to_memcore(payload: dict) -> None:
    """Fire-and-forget MemCore log call. Runs in daemon thread."""
    try:
        requests.post(
            f"http://localhost:{_MEMCORE_PORT}/agentmemory/command/log",
            json=payload,
            timeout=2,
        )
    except requests.exceptions.RequestException:
        pass


def _log(command: str, cwd: str, raw: str, filtered: str, exec_ms: int) -> None:
    """Build and fire the MemCore tracking payload asynchronously."""
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = round((saved / inp * 100) if inp > 0 else 0.0, 1)

    payload = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
        "project": Path(cwd).resolve().name,
        "command": _scrub(command),
        "input_t": inp,
        "output_t": out,
        "saved_t": saved,
        "pct": pct,
        "exec_ms": exec_ms,
    }
    threading.Thread(target=_post_to_memcore, args=(payload,), daemon=True).start()


def _validate_cwd(cwd: str) -> str | None:
    """Return error string if cwd is invalid, else None."""
    resolved = Path(cwd).resolve()
    if not resolved.exists():
        return f"Error: cwd does not exist: {cwd}"
    if not resolved.is_dir():
        return f"Error: cwd is not a directory: {cwd}"
    return None


# ── Primary tool ───────────────────────────────────────────────────────────────

@mcp.tool()
def rtk_run_command(command: str, cwd: str = ".") -> str:
    """Run a shell command with automatic token compression and MemCore logging.

    Supports: git, pytest, ruff, grep/rg, find, pip/uv, docker, ls,
              read (source file), err (generic errors-only), test (generic failures-only).
    Falls back to raw output for any unrecognised command.

    Args:
        command: Full shell command string. Quoted arguments are supported.
        cwd:     Working directory for the command. Defaults to current directory.

    Returns:
        Compressed command output as a string.
    """
    err = _validate_cwd(cwd)
    if err:
        return err

    try:
        args = shlex.split(command)
    except ValueError as e:
        return f"Error: could not parse command: {e}"

    if not args:
        return ""

    main_cmd = args[0]
    cmd_args = args[1:]

    t0 = time.time()
    stdout, stderr, code = execute_command(args, cwd=cwd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    filtered = raw  # default — overwritten below

    try:
        if main_cmd == "git":
            sub = cmd_args[0] if cmd_args else ""
            if sub == "status":
                # Run porcelain only — avoids double subprocess
                p_out, _, _ = execute_command(
                    ["git", "status", "--porcelain"], cwd=cwd
                )
                filtered = _filter_status(p_out)
            elif sub == "log":
                filtered = _filter_log(raw)
            elif sub in ("add", "commit", "push", "pull"):
                filtered = _filter_simple(raw, sub)
            elif sub == "diff":
                # Always use --stat for compact diff summary
                stat_out, _, _ = execute_command(
                    ["git", "diff", "--stat"] + cmd_args[1:], cwd=cwd
                )
                filtered = _filter_diff(stat_out, cmd_args)
            else:
                filtered = raw

        elif main_cmd == "pytest":
            filtered = _filter_pytest(raw)

        elif main_cmd == "ruff":
            sub = cmd_args[0] if cmd_args else "check"
            if sub == "check":
                filtered = _filter_check_json(cmd_args) or _filter_check_text(raw)
            elif sub == "format":
                filtered = _ruff_format(raw)
            else:
                filtered = raw

        elif main_cmd in ("grep", "rg"):
            filtered = _filter_grep(raw)

        elif main_cmd == "find":
            filtered = _filter_find(raw)

        elif main_cmd in ("pip", "uv"):
            sub = cmd_args[0] if cmd_args else ""
            # Handle both `pip list` and `uv pip list`
            effective_sub = cmd_args[1] if main_cmd == "uv" and sub == "pip" and len(cmd_args) > 1 else sub
            if effective_sub == "list":
                # Re-run with JSON flag for reliable parsing
                tool = main_cmd
                json_cmd = (
                    [tool, "pip", "list", "--format", "json"]
                    if tool == "uv"
                    else ["pip", "list", "--format", "json"]
                )
                json_out, _, _ = execute_command(json_cmd, cwd=cwd)
                filtered = _pip_list(json_out)
            elif effective_sub == "show":
                filtered = _pip_show(raw)
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

        elif main_cmd == "ls":
            target = Path(cmd_args[0]) if cmd_args else Path(cwd)
            if not target.is_absolute():
                target = Path(cwd) / target
            if target.exists() and target.is_dir():
                import itertools
                dirs, files_count = [], 0
                for item in sorted(target.iterdir()):
                    if item.name.startswith("."):
                        continue
                    if item.is_dir():
                        try:
                            children = list(itertools.islice(
                                (f for f in item.iterdir() if f.is_file()), 51
                            ))
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
            else:
                filtered = raw

        elif main_cmd == "read":
            # Read a file with code_filter — args[0] is the filepath
            if cmd_args:
                filepath = Path(cwd) / cmd_args[0] if not Path(cmd_args[0]).is_absolute() else Path(cmd_args[0])
                level_str = "minimal"
                for a in cmd_args[1:]:
                    if a in ("none", "minimal", "aggressive"):
                        level_str = a
                try:
                    level = FilterLevel(level_str)
                    file_raw = filepath.read_text(encoding="utf-8", errors="replace")
                    lang_ext = filepath.suffix.lower()
                    from src.pyrtk.cmds.read_cmd import LANGUAGE_MAP
                    language = LANGUAGE_MAP.get(lang_ext, "unknown")
                    filtered = code_filter(file_raw, language, level)
                    raw = file_raw  # use file content as raw for token tracking
                except (FileNotFoundError, PermissionError) as e:
                    return f"Error: {e}"
            else:
                return "Error: pyrtk read requires a file path"

        elif main_cmd == "err":
            filtered = _filter_errors(stdout, stderr)

        elif main_cmd == "test":
            filtered = _filter_test_output(raw, code)

    except Exception as e:
        logger.warning("filter failed for %s: %s", main_cmd, e)
        filtered = raw  # always fall back to raw on filter crash

    _log(command, cwd, raw, filtered, exec_ms)
    return filtered


# ── Utility tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def rtk_gain() -> str:
    """Return token savings summary from MemCore.

    Use this to check how many tokens pyrtk has saved in this project.
    """
    try:
        res = requests.get(
            f"http://localhost:{_MEMCORE_PORT}/agentmemory/gain",
            timeout=3,
        )
        if res.status_code == 200:
            d = res.json()
            return (
                f"pyrtk savings:\n"
                f"  Commands processed : {d.get('total_commands', 0)}\n"
                f"  Tokens saved       : {d.get('total_saved_t', 0):,}\n"
                f"  Average efficiency : {d.get('avg_pct', 0.0):.1f}%"
            )
        return f"MemCore error: HTTP {res.status_code}"
    except requests.exceptions.RequestException as e:
        return f"MemCore unreachable on port {_MEMCORE_PORT}: {e}"


@mcp.tool()
def rtk_passthrough(command: str, cwd: str = ".") -> str:
    """Run a command with zero filtering — full raw output.

    Use when a filter is too aggressive or you need exact command output.
    Output is still logged to MemCore for tracking.

    Args:
        command: Full shell command string.
        cwd:     Working directory.
    """
    err = _validate_cwd(cwd)
    if err:
        return err

    try:
        args = shlex.split(command)
    except ValueError as e:
        return f"Error: could not parse command: {e}"

    t0 = time.time()
    stdout, stderr, code = execute_command(args, cwd=cwd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = stdout + stderr
    _log(command, cwd, raw, raw, exec_ms)  # saved = 0, logged for discovery

    return raw


@mcp.tool()
def rtk_discover(since_hours: int = 24) -> str:
    """Identify commands run in this session that bypassed pyrtk.

    Queries MemCore for recent command history and compares against
    the list of commands pyrtk knows how to filter. Helps you spot
    missed savings.

    Args:
        since_hours: How many hours of history to check (default: 24).
    """
    _COVERED = {
        "git", "pytest", "ruff", "grep", "rg", "find",
        "pip", "uv", "docker", "ls", "read", "err", "test",
    }

    try:
        res = requests.get(
            f"http://localhost:{_MEMCORE_PORT}/agentmemory/command/history",
            params={"hours": since_hours},
            timeout=3,
        )
        if res.status_code != 200:
            return f"MemCore error: HTTP {res.status_code}"

        history = res.json().get("commands", [])
    except requests.exceptions.RequestException as e:
        return f"MemCore unreachable: {e}"

    if not history:
        return f"No commands logged in the last {since_hours}h."

    # Commands that went through pyrtk (logged via rtk_run_command)
    rtk_cmds = {r["command"].split()[0] for r in history}
    bypassed = _COVERED - rtk_cmds

    if not bypassed:
        return f"All tracked commands routed through pyrtk in last {since_hours}h ✓"

    lines = [f"Commands bypassing pyrtk in last {since_hours}h ({len(bypassed)} found):\n"]
    for cmd in sorted(bypassed):
        lines.append(f"  {cmd}")
    lines.append(
        "\nFix: ensure AGENTS.md instructs agy to use rtk_run_command for these commands."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
```

> **Note on `rtk_discover`:** the `/agentmemory/command/history` endpoint must be implemented on your MemCore server if it doesn't already exist. It should accept a `hours` query param and return `{"commands": [{"command": "..."}]}`.

---

### K. `.agents/AGENTS.md` — Full Content

```markdown
# pyrtk — Token Compression Rules

pyrtk is a local MCP server that compresses shell command output before it
enters the agent context window. It saves 60–95% of tokens on common dev
commands by filtering noise and keeping only signal.

## Core Rule

ALWAYS use `rtk_run_command` instead of running shell commands directly.
This applies to every command listed below.

## Supported Commands — Use rtk_run_command for All of These

| Command | Example |
|---|---|
| git | `rtk_run_command("git status", cwd="/path/to/project")` |
| pytest | `rtk_run_command("pytest tests/ -x")` |
| ruff | `rtk_run_command("ruff check src/")` |
| grep / rg | `rtk_run_command("rg 'pattern' src/")` |
| find | `rtk_run_command("find . -name '*.py'")` |
| pip / uv pip | `rtk_run_command("uv pip list")` |
| docker | `rtk_run_command("docker ps")` |
| ls | `rtk_run_command("ls .", cwd="/path/to/dir")` |
| read (source file) | `rtk_run_command("read src/main.py aggressive")` |
| err (any command) | `rtk_run_command("err cargo build")` |
| test (any runner) | `rtk_run_command("test go test ./...")` |

## Unsupported Commands

Pass through `rtk_run_command` anyway — it returns raw output and still
logs the token usage so `rtk_discover` can surface it as a coverage gap.

## Utility Tools

- `rtk_gain()` — check token savings for this session
- `rtk_passthrough("cmd")` — bypass filtering when you need full raw output
- `rtk_discover(since_hours=24)` — find commands that bypassed pyrtk

## Reading Source Files

Prefer `rtk_run_command("read <file>")` over reading files directly.
Use `aggressive` level when you only need function signatures:
`rtk_run_command("read src/main.py aggressive")`

## Notes

- All commands respect the `cwd` parameter — always pass it for project commands
- Exit codes are preserved — a failed command still fails after filtering
- `MEMCORE_PORT` env var controls which MemCore instance is used (default: 3111)
```

---

### L. Bundled Fixes Checklist

Apply these alongside the new modules — they affect every file above.

| Fix | Location | Change |
|---|---|---|
| `shlex.split` | both `mcp_server.py` | `command.split()` → `shlex.split(command)` |
| `datetime.UTC` | both `mcp_server.py`, `tracker.py` | `utcnow()` → `now(datetime.UTC)` |
| `encoding="utf-8"` | `execute_command` in `utils.py` | add `encoding="utf-8", errors="replace"` to subprocess.run |
| `FileNotFoundError` | `execute_command` in `utils.py` | explicit catch before bare `Exception` |
| Tracker threading | both `mcp_server.py` | wrap POST in `threading.Thread(daemon=True)` |
| `pct` rounding | both `mcp_server.py`, `tracker.py` | `round(pct, 1)` before storing |
| Regex precompile | `utils.py`, `docker_cmd.py` | module-level `_ANSI_RE`, `_PS_RE` |
| `×` Windows safety | `filter.py dedup` | `RTK_DEDUP_SYMBOL` env var, default `×`, fallback `x` |
| `structure_only` null | `filter.py` | `val is None → return "null"` |
| `_filter_log` | `git.py` | restrict to `r'^[0-9a-f]{7,}\s'` only |
| `_filter_simple` rejected | `git.py` | add `"rejected"`, `"denied"`, `"fatal"` to error check |
| `ls` sort | `ls_cmd.py`, `mcp_server.py` | `sorted(target.iterdir())` |
| `ls` glob cap | `ls_cmd.py`, `mcp_server.py` | `itertools.islice(..., 51)` |
| `pct` f-string | `tracker.py` | inner single quotes |
| `unused subprocess` | `src/pyrtk/mcp_server.py` | remove `import subprocess` |
| `unused ls run import` | `src/pyrtk/mcp_server.py` | remove `from .cmds.ls_cmd import run` |
| Double subprocess | `mcp_server.py` git status | run `--porcelain` only, skip first call |
| `__init__.py` files | all package dirs | verify exist in `src/`, `src/pyrtk/`, `src/pyrtk/cmds/`, `src/pyrtk/core/` |
| `[project.scripts]` | `pyproject.toml` | add `pyrtk = "main:app"` and `rtk-mcp = "mcp_server:mcp.run"` |
| Description | `pyproject.toml` | replace placeholder with real description |

---

### M. New Unit Tests

Add to `tests/test_new_modules.py`:

```python
# tests/test_new_modules.py
import pytest

from src.pyrtk.core.filter import code_filter, FilterLevel, structure_only, dedup
from src.pyrtk.cmds.grep_cmd import _filter_grep
from src.pyrtk.cmds.find_cmd import _filter_find
from src.pyrtk.cmds.err_cmd import _filter_errors
from src.pyrtk.cmds.test_cmd import _filter_test_output
from src.pyrtk.cmds.pip_cmd import _filter_list, _filter_show


# ── structure_only ──────────────────────────────────────────────────────────

def test_structure_only_null():
    out = structure_only('{"deleted_at": null}')
    assert '"null"' in out
    assert "NoneType" not in out

def test_structure_only_depth_limit():
    # 15-deep nesting should not RecursionError
    deep = '{"a":' * 15 + '"x"' + '}' * 15
    out = structure_only(deep)
    assert "..." in out

def test_structure_only_list():
    out = structure_only('[1, 2, 3]')
    assert '"int"' in out


# ── code_filter ─────────────────────────────────────────────────────────────

def test_code_filter_none_passthrough():
    content = "# comment\ndef foo(): pass"
    assert code_filter(content, "python", FilterLevel.NONE) == content

def test_code_filter_minimal_strips_comments():
    content = "# this is a comment\ndef foo():\n    pass"
    out = code_filter(content, "python", FilterLevel.MINIMAL)
    assert "# this is a comment" not in out
    assert "def foo" in out

def test_code_filter_unknown_language_passthrough():
    content = "some content"
    assert code_filter(content, "unknown", FilterLevel.AGGRESSIVE) == content

def test_code_filter_aggressive_python_keeps_signature():
    content = "def my_func(x: int) -> str:\n    return str(x)\n"
    out = code_filter(content, "python", FilterLevel.AGGRESSIVE)
    assert "def my_func" in out
    assert "..." in out
    assert "return str(x)" not in out

def test_code_filter_aggressive_python_keeps_imports():
    content = "import os\nfrom pathlib import Path\n\ndef foo(): pass\n"
    out = code_filter(content, "python", FilterLevel.AGGRESSIVE)
    assert "import os" in out
    assert "from pathlib" in out


# ── grep_cmd ─────────────────────────────────────────────────────────────────

def test_filter_grep_empty():
    assert _filter_grep("") == "no matches"

def test_filter_grep_groups_by_file():
    raw = "src/a.py:1:match one\nsrc/a.py:2:match two\nsrc/b.py:1:other match"
    out = _filter_grep(raw)
    assert "src/a.py: 2" in out
    assert "src/b.py: 1" in out

def test_filter_grep_single_file_mode():
    raw = "match one\nmatch two\nmatch three"
    out = _filter_grep(raw)
    assert "3 match" in out


# ── find_cmd ─────────────────────────────────────────────────────────────────

def test_filter_find_empty():
    assert _filter_find("") == "no results"

def test_filter_find_small_result_passthrough():
    raw = "./a\n./b\n./c"
    assert _filter_find(raw) == raw

def test_filter_find_groups_by_dir():
    raw = "\n".join(f"./src/file{i}.py" for i in range(20))
    out = _filter_find(raw)
    assert "20 result" in out
    assert "./src:" in out


# ── err_cmd ──────────────────────────────────────────────────────────────────

def test_filter_errors_returns_stderr():
    out = _filter_errors("normal output", "something went wrong")
    assert "something went wrong" in out
    assert "normal output" not in out

def test_filter_errors_captures_error_lines_from_stdout():
    out = _filter_errors("Error: file not found\nNormal line\nFailed to load", "")
    assert "Error: file not found" in out
    assert "Failed to load" in out
    assert "Normal line" not in out

def test_filter_errors_deduplicates():
    stderr = "connection error\nconnection error\nconnection error"
    out = _filter_errors("", stderr)
    assert out.count("connection error") == 1


# ── test_cmd ─────────────────────────────────────────────────────────────────

def test_filter_test_all_passed_exit_0():
    raw = "...\n3 passed in 0.5s"
    out = _filter_test_output(raw, 0)
    assert "passed" in out

def test_filter_test_extracts_pytest_failures():
    raw = (
        "..F\n"
        "=== FAILURES ===\n"
        "____ test_foo ____\n"
        "    assert 1 == 2\n"
        "AssertionError\n"
        "=== short test summary ===\n"
        "FAILED test_foo.py::test_foo\n"
        "1 failed in 0.8s"
    )
    out = _filter_test_output(raw, 1)
    assert "FAILURES" in out
    assert "assert 1 == 2" in out
    assert "1 failed" in out
    assert "..F" not in out  # progress dots stripped

def test_filter_test_collection_error_not_all_passed():
    raw = "ImportError while collecting tests\ncollected 0 items / 1 error"
    out = _filter_test_output(raw, 2)
    assert "all tests passed" not in out
    assert "ImportError" in out


# ── pip_cmd ──────────────────────────────────────────────────────────────────

def test_filter_pip_list_valid_json():
    raw = '[{"name": "requests", "version": "2.31.0"}, {"name": "typer", "version": "0.9.0"}]'
    out = _filter_list(raw)
    assert "2 package" in out
    assert "requests" in out
    assert "typer" in out

def test_filter_pip_list_empty():
    assert _filter_list("[]") == "no packages installed"

def test_filter_pip_list_invalid_json():
    out = _filter_list("not json")
    assert len(out) <= 404  # falls back to raw[:400]

def test_filter_pip_show_keeps_key_fields():
    raw = (
        "Name: requests\n"
        "Version: 2.31.0\n"
        "Summary: HTTP library\n"
        "Home-page: https://requests.readthedocs.io\n"
        "Author: Kenneth Reitz\n"
        "License: Apache 2.0\n"
        "Requires: certifi, urllib3\n"
        "Required-by: httpx\n"
    )
    out = _filter_pip_show(raw)
    assert "Name: requests" in out
    assert "Summary: HTTP library" in out
    assert "Author: Kenneth Reitz" not in out   # not in _SHOW_KEEP
    assert "License: Apache 2.0" not in out     # not in _SHOW_KEEP
```

---

## Additional Findings (Pass 2)

### 23b. Double subprocess call for `git status` in MCP server

The root `mcp_server.py` first runs the full command via `execute_command(args, cwd=cwd)` capturing `stdout/stderr`, then **immediately re-runs** `git status --porcelain` as a second subprocess to get the clean input for `_filter_status`. The first call's output is thrown away entirely.

```python
# current — two spawns for one git status
stdout, stderr, code = execute_command(args, cwd=cwd)   # full git status, unused
...
std_p, _, _ = execute_command(["git", "status", "--porcelain"], cwd=cwd)  # second spawn
filtered = _filter_status(std_p)
```

Fix: run `--porcelain` directly as the only call. The `raw` for token tracking should be synthesised from what a normal `git status` would produce — or just use the porcelain output as the baseline (which is what the CLI already does).

---

### 23c. Input token savings are understated for `git status` and `git diff`

In `git.py run()`, the `raw` variable that goes into `track()` is the **porcelain/stat output** (already compressed), not the full human-readable `git status` / `git diff` output. So `saved_tokens = estimate_tokens(raw) - estimate_tokens(filtered)` compares two already-small strings. Real savings (porcelain vs full status) are typically 10×, but your tracker records near-zero savings for these commands.

Fix: record `input_tokens` based on what the uncompressed command would produce. Easiest approach — pass a separate `baseline` string to `track()` or just swap back to running the full command and converting for tracking only.

---

### 23d. `structure_only` returns `"NoneType"` for JSON `null`

`type(None).__name__` is `"NoneType"` in Python, but `null` is the correct JSON type name. Any JSON with `null` values will produce misleading schema output:

```python
# current
structure_only('{"deleted_at": null}')  →  {"deleted_at": "NoneType"}

# correct
structure_only('{"deleted_at": null}')  →  {"deleted_at": "null"}
```

Fix:
```python
def convert(val, depth=0):
    if depth > 10:
        return "..."
    if val is None:
        return "null"   # handle before type(val).__name__
    if isinstance(val, dict):
        ...
```

---

### 23e. `dual_mode_parse` doesn't save meaningful tokens

The function minifies JSON by removing whitespace (`separators=(',', ':')`) and calls that a saving. But LLM tokenizers don't tokenize whitespace cheaply — `{` `"key"` `:` `"val"` `}` is the same number of tokens pretty-printed or minified. The real savings come from **removing fields** or **replacing values with types**, which is what `structure_only` does. `dual_mode_parse` as written gives the illusion of compression with near-zero actual token reduction.

Either delete it (it's already dead code) or rewrite it to call `structure_only` on the parsed result.

---

### 23f. Unused import `from .cmds.ls_cmd import run` in `src/pyrtk/mcp_server.py`

The import is there but the ls handling in that file is done inline — `run` is never called. Dead import, will confuse static analysers:

```python
# remove this line in src/pyrtk/mcp_server.py
from .cmds.ls_cmd import run
```

---

### 23g. `pct` stored as raw float — produces ugly MemCore records

`(saved / inp * 100)` produces `79.99999999999999`, `80.00000000000001`, etc. Round before storing:

```python
"pct": round((saved / inp * 100) if inp > 0 else 0.0, 1),
```

Same issue in both `mcp_server.py` and `tracker.py`.

---

### 23h. `_filter_pytest` returns `"all tests passed"` on collection errors

When pytest fails with exit code 2 (collection error — bad import, syntax error in a test file), the output typically contains no `"failed"` string, so the filter hits:

```python
return "all tests passed" if "failed" not in raw.lower() else raw[:400]
```

...and returns a false positive. The agent thinks tests passed when the test suite didn't even run.

Fix — check for the actual pytest summary pattern before assuming passing:

```python
if not failures:
    summary = [l for l in lines if re.search(r'\d+ (passed|failed|error|warning)', l)]
    if summary:
        return summary[-1]
    if "no tests ran" in raw.lower() or "collected 0 items" in raw.lower():
        return "no tests collected"
    if "error" in raw.lower():
        return raw[:400]  # collection error — return raw so agent sees it
    return "all tests passed"
```

---

### 23i. `test_mcp.py` has no assertions

It prints output but never verifies it. A print-based smoke test will pass on CI even if `rtk_run_command` returns an empty string or a crash traceback:

```python
# test_mcp.py — add at minimum
out = rtk_run_command("git status")
assert isinstance(out, str), f"Expected str, got {type(out)}"
assert len(out) > 0, "Expected non-empty output"
assert "error" not in out.lower(), f"Unexpected error: {out}"
print("OK:", out)
```

---

### 23j. `_filter_diff` behaves differently between CLI and MCP

In `git.py run()`:
```python
elif sub == "diff" and len(args) == 1:   # args = ["diff"] — only bare diff
    exec_cmd = ["git", "diff", "--stat"]  # substituted to --stat
```

But in `mcp_server.py`, the full original command is already executed before filtering — no `--stat` substitution happens. `_filter_diff` then looks for `files? changed` summary lines which only appear in `--stat` output, so it always falls through to `raw[:400]` for plain `git diff` from MCP. The MCP path is silently returning 400 chars of raw diff instead of the summary.

Fix: run `git diff --stat` explicitly in the MCP path too, same as the CLI does.

---

### 23k. `ls_cmd.py`'s `item.glob('*')` misleads on large directories

`sum(1 for _ in item.glob('*') if _.is_file())` only counts **direct children** of each subdir, not recursively. For `node_modules/`, `.venv/`, or any nested directory this returns `1` or `2` when there are thousands of files. Output like `node_modules/ (1 files)` is actively misleading.

Options:
- Cap with `itertools.islice` and suffix `50+ files` if over the cap
- Or just show `{item.name}/` with no count for large directories

```python
try:
    children = list(itertools.islice(
        (f for f in item.glob('*') if f.is_file()), 51
    ))
    count_str = f"{len(children)} files" if len(children) < 51 else "50+ files"
    dirs.append(f"{item.name}/ ({count_str})")
except PermissionError:
    dirs.append(f"{item.name}/ (no access)")
```

---

### 23l. No `__init__.py` files visible in archive

`main.py` uses `from src.pyrtk import cmds` and `from src.pyrtk.tracker import report`. For these namespace imports to work, `src/__init__.py`, `src/pyrtk/__init__.py`, and `src/pyrtk/cmds/__init__.py` must all exist. They weren't in the extracted files. If they're missing, every import silently fails at runtime with `ModuleNotFoundError`.

Verify with:
```bash
find . -name "__init__.py" | sort
```

Expected output:
```
./src/__init__.py
./src/pyrtk/__init__.py
./src/pyrtk/cmds/__init__.py
./src/pyrtk/core/__init__.py
```

---

## What's Already Good

To be clear on what does NOT need changing:

- MCP server architecture — better than shell hooks for `agy`
- MemCore integration for tracking — elegant, correct fallback
- `_filter_status` using `--porcelain` — reliable machine-readable parsing
- `dedup` logic — clean single-pass implementation
- `execute_command` with timeout and `stdin=subprocess.DEVNULL` — correct
- Tracker silently swallowing connection errors — correct behavior
- Import structure and module separation — clean
- `shlex.split()` (post-fix) — correct
- Exit code propagation in `git.py` and `pytest_cmd.py` — correct

---

*Reviewed against rtk-ai/rtk v0.42.4 architecture. All issues verified against uploaded source.*