# main.py
import typer
from src.pyrtk import cmds
from src.pyrtk.tracker import report

app = typer.Typer(
    help="pyrtk — local RTK-equivalent, Python edition",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
)

@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def git(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")):
    """Proxy git command with compact output."""
    cmds.git.run(ctx.args, verbose)

@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def pytest(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")):
    """Proxy pytest command; show failures only."""
    cmds.pytest_cmd.run(ctx.args, verbose)

@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def ls(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")):
    """Compress file listings into tree structure."""
    cmds.ls_cmd.run(ctx.args, verbose)

@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def docker(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")):
    """Proxy docker command."""
    cmds.docker_cmd.run(ctx.args, verbose)

@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def ruff(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")):
    """Proxy ruff check with grouped-by-file output."""
    cmds.ruff_cmd.run(ctx.args, verbose)

@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def grep(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")):
    """Proxy grep/rg with grouped-by-file output."""
    cmds.grep_cmd.run(ctx.args, verbose)

@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def pip(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")):
    """Proxy pip list with compact table."""
    cmds.pip_cmd.run(ctx.args, verbose)

@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def find(ctx: typer.Context, verbose: bool = typer.Option(False, "-v")):
    """Proxy find with directory-collapsed summary."""
    cmds.find_cmd.run(ctx.args, verbose)

@app.command()
def gain():
    """Show token savings report fetched from MemCore."""
    report()

@app.command()
def dedup(file: str = typer.Argument(None)):
    """Deduplicate consecutive lines from a file or stdin."""
    from src.pyrtk.core.filter import dedup as run_dedup
    import sys
    if file:
        with open(file, "r") as f:
            content = f.read()
    else:
        content = sys.stdin.read()
    print(run_dedup(content))

@app.command()
def structure(file: str = typer.Argument(None)):
    """Extract structural schema from a JSON file or stdin."""
    from src.pyrtk.core.filter import structure_only
    import sys
    if file:
        with open(file, "r") as f:
            content = f.read()
    else:
        content = sys.stdin.read()
    print(structure_only(content))

if __name__ == "__main__":
    app()
