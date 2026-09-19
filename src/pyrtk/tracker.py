# src/pyrtk/tracker.py
from __future__ import annotations

import datetime
import logging
import os
import threading
from pathlib import Path

import requests

from .core.utils import estimate_tokens, scrub_secrets
from .registry import registry

logger = logging.getLogger(__name__)


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
    """Async tracking function. Logs metadata to local SQLite and MemCore."""
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = round((saved / inp * 100) if inp > 0 else 0.0, 1)

    project = Path(cwd).resolve().name
    now_str = datetime.datetime.now(datetime.UTC).isoformat() + "Z"
    clean_cmd = scrub_secrets(original_cmd)

    # Persist locally in SQLite registry first (guaranteed offline telemetry)
    registry.log_command(
        timestamp=now_str,
        project=project,
        command=clean_cmd,
        input_t=inp,
        output_t=out,
        saved_t=saved,
        pct=pct,
        exec_ms=exec_ms,
    )

    payload = {
        "timestamp": now_str,
        "project": project,
        "command": clean_cmd,
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
    data = None
    source = "MemCore"

    try:
        res = requests.get(url, timeout=2)
        if res.status_code == 200:
            data = res.json()
    except requests.exceptions.RequestException:
        pass

    if not data:
        # Fallback to local SQLite command history
        data = registry.get_local_stats()
        source = "Local SQLite"

    console = Console()
    table = Table(title=f"pyrtk Token Savings ({source})")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Commands Processed", str(data.get("total_commands", 0)))
    table.add_row("Total Input Tokens", f"{data.get('total_input_t', 0):,}")
    table.add_row("Total Output Tokens", f"{data.get('total_output_t', 0):,}")
    table.add_row("Total Tokens Saved", f"{data.get('total_saved_t', 0):,}")
    table.add_row("Average Efficiency", f"{data.get('avg_pct', 0.0):.1f}%")

    console.print(table)
