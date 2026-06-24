# src/pyrtk/cmds/read_cmd.py
from __future__ import annotations

import os
import sys
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
        print("Usage: pyrtk read <file> [none|minimal|aggressive]", file=sys.stderr)
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
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        raise SystemExit(1)
    if not path.is_file():
        print(f"Error: not a file: {filepath}", file=sys.stderr)
        raise SystemExit(1)

    t0 = time.time()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        print(f"Error: permission denied: {filepath}", file=sys.stderr)
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
            file=sys.stderr,
        )

    print(filtered)
    track(
        f"read {filepath}",
        f"pyrtk read {filepath} --level {level.value}",
        raw,
        filtered,
        exec_ms,
    )
