# pyrtk - Python Token Killer (v0.2.0)

A local proxy CLI and Model Context Protocol (MCP) server built to intercept and compress development command outputs before they enter an LLM context window, cutting noisy output tokens by 60%-95%.

---

## Features

### 1. Model Context Protocol (MCP) Server
Exposes 7 tools for AI coding assistants (Antigravity, Gemini CLI, Claude Code, etc.):
- **`rtk_run_command(command, cwd=".", background=False)`**: Executes commands through the unified dispatcher, compresses output, scrubs secrets, and logs telemetry to MemCore. Auto-detects long-running servers (`npm/yarn/pnpm/bun run dev|start|watch`, `docker compose up`, `uvicorn`, `gunicorn`, `fastapi dev`, `python -m http.server`, `node --watch`) and detaches to background automatically.
- **`rtk_check_background(handle_id, tail_lines=20)`**: Checks live status and exit code of a background process in SQLite `registry.db` (falling back to `psutil` PID + creation-time checks) and tails stdout/stderr logs.
- **`rtk_kill_background(handle_id)`**: Terminates a background process registered in `registry.db`.
- **`rtk_retrieve(ref)`**: Recovers full uncompressed payloads behind a `ccr_<hash>` reference from local SQLite CCR cache or MemCore (`/agentmemory/ccr/retrieve`).
- **`rtk_gain()`**: Queries MemCore (`/agentmemory/gain`) with local SQLite registry fallback to summarize processed commands, tokens saved, and average efficiency.
- **`rtk_passthrough(command, cwd=".")`**: Runs a command with zero filtering (full raw output) while still recording execution metadata.
- **`rtk_discover(since_hours=24)`**: Audits recent command history from MemCore or local SQLite to report covered vs uncovered commands.

### 2. Background Execution & Process Registry
- Resolves Windows `.cmd` / `.bat` / `.exe` shims and monorepo `.venv` binaries cleanly.
- Uses sanitized filenames under `.pyrtk_logs/` (`<cmd>_<hash>_stdout.log` / `_stderr.log`) with secret redaction.
- Reuses SQLite connections in `src/pyrtk/registry.py`, indexes registry tables, sweeps dead PIDs, and prunes finished rows/logs after 7 days (stale/unobserved rows after 28 days).

### 3. JSON Compression, CCR Cache & Tee Logs
- Recursively detects JSON arrays of objects (top-level or wrapped) and compresses them into `{schema, rows, defaults}` columnar form.
- Oversized JSON arrays truncate the middle and store the full raw payload in the local CCR cache (default 24h TTL via `PYRTK_CCR_TTL_SECONDS`, recoverable via `rtk_retrieve(ref)`). Does not alter `read` output on `.json` files.
- On command failures, saves scrubbed raw output to `~/.pyrtk/tee/` and prunes old tee logs automatically.

### 4. Supported CLI Proxy Commands
- **`git`**: Porcelain status, smart `--stat` branch diff injection, compact commit logs, short-circuit `add`/`commit`/`push`/`pull`.
- **`pytest` / `test`**: Collapses test noise to failure summaries and tracebacks (`pytest`, `jest`, `go test`, `rspec`, etc.).
- **`cargo`**: Filters `cargo build`, `cargo clippy`, and `cargo test`.
- **`ruff`**: Runs `ruff check` in JSON mode and groups lint violations, plus compact `ruff format` output.
- **`grep` / `rg`**: Groups matches by file with counts.
- **`find`**: Condenses file searches with native Python fallback on Windows.
- **`pip` / `uv pip`**: Structures package lists and metadata cleanly.
- **`docker`**: Formats `docker ps` into compact tables.
- **`ls`**: Compresses directory listings.
- **`read`**: Reads source files with AST-aware Python structural compression (`none`, `minimal`, `aggressive`).
- **`err` / `tail` / `json`**: Generic error-line filter, tail summaries, and schema/columnar JSON compression.

### 5. Utility CLI Commands
- `pyrtk gain`: Prints token savings summary.
- `pyrtk dedup [file]`: Collapses consecutive identical lines.
- `pyrtk structure [file]`: Summarizes JSON schema structure.
- `pyrtk version`: Prints `pyrtk 0.2.0`.

### 6. Custom Logging
Writes timestamped ISO-8601 UTC logs with 5 MB rotation (`pyrtk.log.1`) to `pyrtk.log` (or `~/.pyrtk/pyrtk.log`):
```text
[YYYY-MM-DDTHH:mm:ss.sssZ] [TAG] message
```

---

## Installation & Setup

### Prerequisites
- Python `>=3.12`
- [uv](https://github.com/astral-sh/uv)

### Local Environment & Global Editable Install
```powershell
# Sync dev + runtime dependencies
uv sync

# Run test suite, type checker, and linter
uv run pytest
uv run mypy src
uv run ruff check src tests

# Install globally as an editable CLI tool (`pyrtk`, `pyrtk-mcp`, `rtk-mcp`)
uv tool install --force --editable .
```

### Entrypoints (`pyproject.toml`)
1. `pyrtk`: CLI proxy (`pyrtk.cli:app`)
2. `pyrtk-mcp` / `rtk-mcp`: MCP stdio server (`pyrtk.mcp_server:main`)

---

## Usage

### CLI Usage
```powershell
pyrtk git status
pyrtk read src/pyrtk/cli.py aggressive
pyrtk grep "def " src/
```

### MCP Client Registration (`mcp_config.json`)
```json
{
  "mcpServers": {
    "pyrtk": {
      "command": "D:/Personal Project/rtk/.venv/Scripts/python.exe",
      "args": [
        "D:/Personal Project/rtk/mcp_server.py"
      ],
      "env": {
        "MEMCORE_PORT": "3111"
      },
      "cwd": "D:/Personal Project/rtk"
    }
  }
}
```

---

## Architecture Details

- **Unified Core Dispatch**: Both CLI (`src/pyrtk/cli.py`) and MCP (`src/pyrtk/mcp_server.py`) execute through `src/pyrtk/core/dispatcher.py` and track telemetry through a single pipeline.
- **Persistent HTTP Session & Exit Flush**: `src/pyrtk/tracker.py` reuses a `requests.Session` with background async posting to MemCore (`/agentmemory/command/log`) and flushes pending telemetry cleanly on CLI exit, never blocking execution if MemCore is offline.
- **Windows Quote Handling & Secret Redaction**: `split_command` preserves nested quotes and Windows escapes, while `scrub_secrets` sanitizes tokens/keys across command logs, tee files, and background outputs.
- **Token Estimator**: Uses `len(text) // 4` heuristic against actual raw command output sizes.
- **CacheAligner Convention**: Keep static prompt instructions/schemas first and byte-identical across turns, dynamic results after, and timestamps last to maximize KV-cache hits.
