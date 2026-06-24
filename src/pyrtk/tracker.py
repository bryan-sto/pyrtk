# src/pyrtk/tracker.py
from __future__ import annotations

import datetime
import logging
import os
import re
import threading
from pathlib import Path

import requests

from .core.utils import estimate_tokens

logger = logging.getLogger(__name__)

_SECRET_RE = re.compile(
    r"(bearer|authorization|token|password|secret|key|auth)(?:\s+|=)\S+",
    re.IGNORECASE,
)


def _scrub(cmd: str) -> str:
    """Remove sensitive credential patterns from command string."""
    return _SECRET_RE.sub(r"\1 [REDACTED]", cmd)


def _post_to_memcore(payload: dict, port: str) -> None:
    """Synchronous POST handler called in background thread."""
    url = f"http://localhost:{port}/agentmemory/command/log"
    try:
        requests.post(url, json=payload, timeout=2)
    except requests.exceptions.RequestException:
        pass


def track(
    original_cmd: str,
    rtk_cmd: str,
    raw: str,
    filtered: str,
    exec_ms: int,
    cwd: str = ".",
) -> None:
    """Async tracking function. Logs metadata to local MemCore."""
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = round((saved / inp * 100) if inp > 0 else 0.0, 1)

    project = Path(cwd).resolve().name

    payload = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
        "project": project,
        "command": _scrub(original_cmd),
        "input_t": inp,
        "output_t": out,
        "saved_t": saved,
        "pct": pct,
        "exec_ms": exec_ms,
    }

    port = os.getenv("MEMCORE_PORT", "3111")
    threading.Thread(
        target=_post_to_memcore,
        args=(payload, port),
        daemon=True,
    ).start()


def report() -> None:
    """Prints a formatted report of token savings to stdout."""
    from rich.console import Console
    from rich.table import Table

    port = os.getenv("MEMCORE_PORT", "3111")
    url = f"http://localhost:{port}/agentmemory/gain"

    try:
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            console = Console()
            table = Table(title="pyrtk Token Savings (MemCore Integrated)")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="magenta")

            table.add_row("Commands Processed", str(data.get("total_commands", 0)))
            table.add_row("Total Input Tokens", f"{data.get('total_input_t', 0):,}")
            table.add_row("Total Output Tokens", f"{data.get('total_output_t', 0):,}")
            table.add_row("Total Tokens Saved", f"{data.get('total_saved_t', 0):,}")
            table.add_row("Average Efficiency", f"{data.get('avg_pct', 0.0):.1f}%")

            console.print(table)
        else:
            print(f"Error: MemCore returned status code {res.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to MemCore server on port {port}: {str(e)}")
