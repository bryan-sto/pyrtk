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
