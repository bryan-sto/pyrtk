# src/pyrtk/tracker.py
from __future__ import annotations

import atexit
import concurrent.futures
import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests

from .core.utils import estimate_tokens, scrub_secrets, utc_now_iso
from .registry import registry

logger = logging.getLogger(__name__)

_ORIG_REQUESTS_POST = requests.post
_session_lock = threading.Lock()
_session: requests.Session | None = None

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_pending_futures: set[Future[None]] = set()
_FLUSH_TIMEOUT_S = 0.2


def _get_session() -> requests.Session:
    """Return a shared thread-safe requests.Session instance."""
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = requests.Session()
    return _session


def _get_executor() -> ThreadPoolExecutor:
    """Return a bounded ThreadPoolExecutor for telemetry POSTs."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pyrtk-telemetry")
    return _executor


def _flush_telemetry(timeout: float = _FLUSH_TIMEOUT_S) -> None:
    """Wait briefly for pending telemetry futures on exit without blocking."""
    with _executor_lock:
        pending = list(_pending_futures)
    if pending:
        concurrent.futures.wait(pending, timeout=timeout)


atexit.register(_flush_telemetry)


def _post_to_memcore(payload: dict[str, Any], port: str) -> None:
    """Synchronous POST handler called in background thread."""
    url = f"http://localhost:{port}/agentmemory/command/log"
    try:
        if requests.post is not _ORIG_REQUESTS_POST:
            requests.post(url, json=payload, timeout=2)
        else:
            _get_session().post(url, json=payload, timeout=2)
    except requests.exceptions.RequestException:
        pass


def track(
    original_cmd: str,
    rtk_cmd: str,
    raw: str,
    filtered: str,
    exec_ms: int,
    cwd: str = ".",
) -> dict[str, Any]:
    """Async tracking function. Logs metadata to local SQLite and MemCore."""
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = round((saved / inp * 100) if inp > 0 else 0.0, 1)

    project = Path(cwd).resolve().name
    now_str = utc_now_iso()
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
    executor = _get_executor()
    future = executor.submit(_post_to_memcore, payload, port)
    with _executor_lock:
        _pending_futures.add(future)

    def _on_done(done_future: Future[None]) -> None:
        with _executor_lock:
            _pending_futures.discard(done_future)

    future.add_done_callback(_on_done)
    return payload


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
