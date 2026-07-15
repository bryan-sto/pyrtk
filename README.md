# pyrtk — Python Token Killer

A local proxy CLI and Model Context Protocol (MCP) server designed to intercept and compress development command outputs. It reduces context token usage by 60%–95% before output enters the LLM's context window.

This project is intended as a learning experience in writing MCP servers and CLI proxies, and was 100% vibe coded with Gemini. It is a Python-based implementation and extension of the original Rust-based [rtk (Rust Token Killer)](https://github.com/coder/rtk).

---

## Features

### 1. Model Context Protocol (MCP) Server
Exposes tools for direct integration with AI coding assistants (like Google Antigravity, Claude Code, etc.):
- **`rtk_run_command(command, cwd, background=False)`**: Runs a command, intercepts it, compresses output, and logs to MemCore. Auto-detects long-running/dev-server commands (`npm run dev`, `uvicorn`, `docker compose up`, etc.) and switches to background mode automatically even if `background` isn't passed explicitly.
- **`rtk_check_background(handle_id, tail_lines=20)`**: Checks whether a background process (started via `rtk_run_command(background=True)`) is still alive, returns its exit code once finished, and tails its stdout/stderr logs. Backed by a small SQLite process registry so handles survive across tool calls.
- **`rtk_retrieve(ref)`**: Recovers the original, uncompressed data behind a `ccr_<hash>` reference left by the JSON compressor or a truncated background log. Raises an explicit error if the ref has expired or doesn't exist — never fails silently.
- **`rtk_gain()`**: Queries MemCore to show total processed commands, total tokens saved, and average efficiency.
- **`rtk_passthrough(command, cwd)`**: Runs any command with zero filtering (full raw output), while still logging the execution metadata to MemCore.
- **`rtk_discover(since_hours)`**: Identifies commands run recently that bypassed `pyrtk` to highlight missed token savings.

### 1a. Background Process Handling
Commands that stay alive past their initial output (dev servers, `uv run`, watch tasks) are fully detached: no pipes, stdout/stderr redirected to `.pyrtk_logs/`, registered in a local SQLite registry (`registry.db`) keyed by a `handle_id`. This avoids the classic hang where a parent process blocks forever waiting for EOF on a pipe a background child keeps open. Finished process rows and their log files are automatically evicted after 7 days (stale/unobserved rows after 28 days) so `.pyrtk_logs/` doesn't grow unbounded.

### 1b. JSON Compression & CCR Cache
Any command output that is valid JSON gets automatically passed through a columnar compressor: arrays of similarly-shaped objects (API responses, DB rows) are converted into a `{schema, rows, defaults}` form, with dominant repeated values hoisted out and shown once. Detection is recursive, so wrapped responses like `{"data": [...]}` or `{"matches": [...]}` are compressed too, not just bare top-level arrays. Oversized arrays are truncated (keep-first-N / keep-last-N) with the omitted middle stored in a local reversible cache (CCR) — recoverable at any time via `rtk_retrieve(ref)`. This does **not** apply to `read` output, so reading an actual `.json` file always shows you the real file content, not a compressed summary. The CCR cache is TTL-evicted (default 24h, `PYRTK_CCR_TTL_SECONDS` override) with a size cap as a backstop.

### 2. Supported CLI Proxy Commands
`pyrtk` wraps and filters output for the following tools:
- **`git`**:
  - `git status`: Intercepts and parses porcelain format.
  - `git diff`: Dynamically appends `--stat` to revision/branch diffs to save context tokens unless an explicit formatting option (`--stat`, `--name-only`, `--name-status`, `-p`, `--patch`) is provided.
  - `git log`: Extracts hash, author, date, and commit messages, filtering out noise.
  - `git add` / `commit` / `push` / `pull`: Short-circuit responses and logs errors.
- **`pytest`**: Collapses test outputs, displaying failures and traceback lines only.
- **`ruff`**: Runs `ruff check` in JSON mode, grouping violations by code and file.
- **`grep` / `rg`**: Summarizes matches, grouping results by filename and showing counts.
- **`find`**: Condenses directory tree searches and outputs summary paths.
- **`pip` / `uv pip`**: Structures installed packages in a neat, compact table format.
- **`docker`**: Formats `docker ps` outputs by removing empty/redundant spaces.
- **`ls`**: Compresses directory listings into a clean tree structure.
- **`read`**: Reads source files with language-aware compression (`none`, `minimal` to strip comments, `aggressive` to strip function bodies and keep signatures/imports).
- **`err`**: Wraps any arbitrary CLI tool to output stderr and error-pattern lines only.
- **`test`**: Generic test runner proxy showing failure lines only (Jest, Go test, RSpec, pytest, etc.).

### 3. Utility CLI Tools
- `pyrtk gain`: Prints local session token savings.
- `pyrtk dedup [file]`: Deduplicates consecutive identical lines from a file or stdin.
- `pyrtk structure [file]`: Extracts structural schema from JSON data.
- `pyrtk version`: Prints the current version.

### 4. Custom Logging
All actions, successes, passthroughs, and filter errors log directly to [pyrtk.log] in the project root.
Logs use the standard MemCore format:
```text
[YYYY-MM-DDTHH:mm:ss.sssZ] [TAG] message
```

---

## Installation & Setup

### Prerequisites
- Python `>=3.12`
- [uv](https://github.com/astral-sh/uv) (recommended)
- `psutil` (declared in `pyproject.toml`) — used for cross-platform liveness checks on background processes

### Local Environment Setup
Sync the dependencies and build the virtual environment using `uv`:
```powershell
# Sync project dependencies
uv sync

# Run tests to verify the setup
uv run pytest
```

### CLI Entrypoints
The package defines two script entrypoints in `pyproject.toml`:
1. **`pyrtk`**: CLI wrapper (`main:app`)
2. **`rtk-mcp`**: MCP server runner (`mcp_server:mcp.run`)

---

## Usage

### 1. CLI Usage
Run commands through the `pyrtk` proxy:
```powershell
uv run pyrtk git status
uv run pyrtk read src/main.py aggressive
uv run pyrtk grep "def " src/
```

### 2. MCP Server Usage
Add `rtk-mcp` to your LLM client configuration (e.g. `claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "pyrtk": {
      "command": "uv",
      "args": [
        "--directory",
        "D:\\your_directory\\rtk",
        "run",
        "rtk-mcp"
      ]
    }
  }
}
```

---

## Architecture Details

- **Token Estimator**: The project uses custom token estimation logic in `src/pyrtk/core/utils.py` (a `len(text) // 4` character heuristic, not a real tokenizer) to calculate raw/filtered context sizes and log the savings ratio. Savings for `git status`/`git diff` are measured against the actual raw output length — earlier versions used a fabricated baseline for these two commands, which has since been corrected.
- **MemCore Tracking Daemon**: Commands run under `rtk_run_command` trigger background daemon threads to report telemetry to a local MemCore SQLite logger on port `3111` (or `MEMCORE_PORT` env override). If MemCore is unreachable, the post fails silently and the command result is still returned — telemetry is best-effort, never blocking.
- **Windows Shell Parsing**: The MCP command parser uses `shlex.split` tuned for Windows compatibility, preserving quoted arguments and handling backslashes correctly.
- **Process Registry** (`src/pyrtk/registry.py`): SQLite-backed (`registry.db`), tracks background process metadata and the CCR cache. Keeps live `Popen` handles in memory for accurate exit-code recovery; falls back to `psutil` pid checks if the server restarted and the in-memory handle is gone (exit code is unrecoverable in that fallback path on Windows).
- **Prompt/Context Assembly Convention (CacheAligner)**: when constructing prompts or injecting tool output, keep static content (instructions, schemas) first and byte-identical across calls, dynamic content after, and timestamps/session data at the very end — improves LLM provider KV-cache hit rates. This is a convention followed by callers, not something pyrtk enforces mechanically.