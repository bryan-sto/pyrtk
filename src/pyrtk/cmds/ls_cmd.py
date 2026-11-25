# src/pyrtk/cmds/ls_cmd.py
from __future__ import annotations


def run(args: list[str], verbose: bool = False) -> None:
    """Compress directory listing into tree structure or show single-file size."""
    from ..core.dispatcher import run_cli_command

    run_cli_command("ls", args, verbose=verbose, error_to_stderr=True)
