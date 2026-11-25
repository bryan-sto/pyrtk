# src/pyrtk/cmds/read_cmd.py
from __future__ import annotations

import sys

# Extension -> language key for code_filter
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

    from ..core.dispatcher import run_cli_command

    run_cli_command("read", args, verbose=verbose, error_to_stderr=True)
