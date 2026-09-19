# src/pyrtk/registry.py
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

# Documenting tradeoff:
# Windows cannot recover exit codes from raw pids after the process terminates if the process handle is lost.
# The in-memory live_handles dict preserves subprocess.Popen objects during the lifetime of the MCP server,
# allowing real exit codes to be polled. If the server restarts, we fall back to querying liveness of the PID
# via SQLite and psutil, checking creation time to guard against Windows PID recycling.

@dataclass
class ProcessEntry:
    handle_id: str
    pid: int
    cmd: list[str]
    stdout_log: str
    stderr_log: str
    started_at: float
    ended_at: float | None = None
    exit_code: int | None = None
    live_handle: subprocess.Popen[Any] | None = None


class ProcessRegistry:
    def __init__(self, db_dir: Path | None = None):
        if db_dir is None:
            # Default to user home directory ~/.pyrtk/ or fallback to existing .pyrtk_logs
            fallback = Path(__file__).parent.parent.parent / ".pyrtk_logs"
            if fallback.exists():
                db_dir = fallback
            else:
                db_dir = Path.home() / ".pyrtk"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / "registry.db"
        self._live_handles: dict[str, subprocess.Popen] = {}
        self._init_db()
        # Clean startup sweep of expired cache
        self.ccr_sweep()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 10000;")
        except Exception:
            pass
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS background_processes (
                    handle_id   TEXT PRIMARY KEY,
                    pid         INTEGER NOT NULL,
                    cmd         TEXT NOT NULL,
                    stdout_log  TEXT NOT NULL,
                    stderr_log  TEXT NOT NULL,
                    started_at  REAL NOT NULL,
                    ended_at    REAL,
                    exit_code   INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ccr_cache (
                    ref         TEXT PRIMARY KEY,
                    original    BLOB NOT NULL,
                    created_at  REAL NOT NULL,
                    ttl_seconds INTEGER DEFAULT 86400,
                    source_tool TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS command_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TEXT NOT NULL,
                    project      TEXT NOT NULL,
                    command      TEXT NOT NULL,
                    input_t      INTEGER NOT NULL,
                    output_t     INTEGER NOT NULL,
                    saved_t      INTEGER NOT NULL,
                    pct          REAL NOT NULL,
                    exec_ms      INTEGER NOT NULL
                )
            """)

    def register(self, proc: subprocess.Popen, cmd: list[str], stdout_path: str, stderr_path: str) -> str:
        handle_id = str(uuid.uuid4())
        started_at = time.time()
        cmd_json = json.dumps(cmd)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO background_processes (handle_id, pid, cmd, stdout_log, stderr_log, started_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (handle_id, proc.pid, cmd_json, stdout_path, stderr_path, started_at)
            )
        self._live_handles[handle_id] = proc
        return handle_id

    def get(self, handle_id: str) -> ProcessEntry:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT handle_id, pid, cmd, stdout_log, stderr_log, started_at, ended_at, exit_code
                FROM background_processes WHERE handle_id = ?
                """,
                (handle_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise KeyError(f"Unknown handle_id: {handle_id}")

            h_id, pid, cmd_str, stdout_log, stderr_log, started_at, ended_at, exit_code = row
            cmd = json.loads(cmd_str)
            live_handle = self._live_handles.get(handle_id)
            return ProcessEntry(
                handle_id=h_id,
                pid=pid,
                cmd=cmd,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                started_at=started_at,
                ended_at=ended_at,
                exit_code=exit_code,
                live_handle=live_handle
            )

    def update_status(self, handle_id: str, ended_at: float, exit_code: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE background_processes
                SET ended_at = ?, exit_code = ?
                WHERE handle_id = ?
                """,
                (ended_at, exit_code, handle_id)
            )
        # Clean up in-memory handle if it is done
        self._live_handles.pop(handle_id, None)

    def terminate(self, handle_id: str) -> bool:
        """Terminate a running process and its children by handle_id."""
        entry = self.get(handle_id)
        killed = False

        if entry.live_handle is not None and entry.live_handle.poll() is None:
            try:
                parent = psutil.Process(entry.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()
                gone, alive = psutil.wait_procs([parent], timeout=2)
                for p in alive:
                    p.kill()
                killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                try:
                    entry.live_handle.terminate()
                    killed = True
                except Exception:
                    pass
        else:
            # Fallback for process started in earlier server session
            try:
                parent = psutil.Process(entry.pid)
                # Verify PID was not recycled (started_at delta < 3.0s)
                if abs(parent.create_time() - entry.started_at) < 3.0:
                    for child in parent.children(recursive=True):
                        child.terminate()
                    parent.terminate()
                    gone, alive = psutil.wait_procs([parent], timeout=2)
                    for p in alive:
                        p.kill()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                pass

        self.update_status(handle_id, time.time(), -9)
        return killed

    def log_command(
        self,
        timestamp: str,
        project: str,
        command: str,
        input_t: int,
        output_t: int,
        saved_t: int,
        pct: float,
        exec_ms: int,
    ) -> None:
        """Persist command telemetry to local SQLite command_history."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO command_history (timestamp, project, command, input_t, output_t, saved_t, pct, exec_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (timestamp, project, command, input_t, output_t, saved_t, pct, exec_ms),
                )
        except Exception:
            pass

    def get_local_stats(self) -> dict[str, Any]:
        """Aggregate local command savings stats."""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*), SUM(input_t), SUM(output_t), SUM(saved_t), AVG(pct)
                    FROM command_history
                """)
                row = cursor.fetchone()
                if row and row[0] is not None and row[0] > 0:
                    return {
                        "total_commands": row[0],
                        "total_input_t": row[1] or 0,
                        "total_output_t": row[2] or 0,
                        "total_saved_t": row[3] or 0,
                        "avg_pct": round(row[4] or 0.0, 1),
                    }
        except Exception:
            pass
        return {
            "total_commands": 0,
            "total_input_t": 0,
            "total_output_t": 0,
            "total_saved_t": 0,
            "avg_pct": 0.0,
        }

    def ccr_store(self, data: Any, source_tool: str = "json_compress", ttl: int = 86400) -> str:
        ser = json.dumps(data)
        compressed = zlib.compress(ser.encode("utf-8"))
        h = hashlib.sha256(ser.encode("utf-8")).hexdigest()[:16]
        ref = f"ccr_{h}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ccr_cache (ref, original, created_at, ttl_seconds, source_tool)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ref, compressed, now, ttl, source_tool)
            )
        self.ccr_sweep()
        return ref

    def ccr_retrieve(self, ref: str) -> Any:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT original, created_at, ttl_seconds FROM ccr_cache WHERE ref = ?",
                (ref,)
            )
            row = cursor.fetchone()
            if not row:
                raise KeyError(f"Cache miss or expired ref: {ref}")
            original, created_at, ttl = row
            if time.time() > created_at + ttl:
                conn.execute("DELETE FROM ccr_cache WHERE ref = ?", (ref,))
                raise KeyError(f"Cache expired for ref: {ref}")
            decompressed = zlib.decompress(original).decode("utf-8")
            return json.loads(decompressed)

    def ccr_sweep(self) -> None:
        now = time.time()
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM ccr_cache WHERE created_at + ttl_seconds < ?", (now,))
            db_size = self.db_path.stat().st_size
            if db_size > 500 * 1024 * 1024:
                with self._connect() as conn:
                    conn.execute("""
                        DELETE FROM ccr_cache
                        WHERE ref IN (
                            SELECT ref FROM ccr_cache
                            ORDER BY created_at ASC
                            LIMIT (SELECT COUNT(*) FROM ccr_cache) / 5
                        )
                    """)
        except Exception:
            pass
        self.process_sweep()

    def process_sweep(self, max_age_seconds: int = 7 * 86400) -> None:
        """Evict finished background_processes rows older than max_age_seconds
        and delete their stdout/stderr log files. Clean up abandoned processes."""
        cutoff = time.time() - max_age_seconds
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT handle_id, stdout_log, stderr_log FROM background_processes
                    WHERE ended_at IS NOT NULL AND ended_at < ?
                    """,
                    (cutoff,)
                )
                rows = cursor.fetchall()
                for handle_id, stdout_log, stderr_log in rows:
                    for log_path in (stdout_log, stderr_log):
                        try:
                            p = Path(log_path)
                            if p.exists():
                                p.unlink()
                        except Exception:
                            pass
                conn.execute(
                    "DELETE FROM background_processes WHERE ended_at IS NOT NULL AND ended_at < ?",
                    (cutoff,)
                )

                stale_cutoff = time.time() - (max_age_seconds * 4)
                cursor.execute(
                    """
                    SELECT handle_id, pid, started_at FROM background_processes
                    WHERE ended_at IS NULL AND started_at < ?
                    """,
                    (stale_cutoff,)
                )
                stale_rows = cursor.fetchall()
                for handle_id, pid, started_at in stale_rows:
                    self._live_handles.pop(handle_id, None)
                    # Attempt termination of the stale OS process if still running
                    try:
                        p = psutil.Process(pid)
                        if abs(p.create_time() - started_at) < 3.0:
                            p.terminate()
                    except Exception:
                        pass

                conn.execute(
                    "UPDATE background_processes SET ended_at = ?, exit_code = -1 "
                    "WHERE ended_at IS NULL AND started_at < ?",
                    (time.time(), stale_cutoff)
                )
        except Exception:
            pass


registry = ProcessRegistry()
