# pyrtk — Python Token Killer

A local proxy CLI and Model Context Protocol (MCP) server designed to intercept and compress development command outputs. It reduces context token usage by 60%–95% before output enters the LLM's context window.

This project is a Python-based implementation and extension of the original Rust-based [rtk (Rust Token Killer)](https://github.com/coder/rtk).

---

## Features

### 1. Model Context Protocol (MCP) Server
Exposes tools for direct integration with AI coding assistants (like Google Antigravity, Claude Code, etc.):
- **`rtk_run_command(command, cwd)`**: Runs a command, intercepts it, compresses output, and logs to MemCore.
- **`rtk_gain()`**: Queries MemCore to show total processed commands, total tokens saved, and average efficiency.
- **`rtk_passthrough(command, cwd)`**: Runs any command with zero filtering (full raw output), while still logging the execution metadata to MemCore.
- **`rtk_discover(since_hours)`**: Identifies commands run recently that bypassed `pyrtk` to highlight missed token savings.

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
All actions, successes, passthroughs, and filter errors log directly to [pyrtk.log](file:///D:/Personal%20Project/rtk/pyrtk.log) in the project root.
Logs use the standard MemCore format:
```text
[YYYY-MM-DDTHH:mm:ss.sssZ] [TAG] message
```

---

## Installation & Setup

### Prerequisites
- Python `>=3.12`
- [uv](https://github.com/astral-sh/uv) (recommended)

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
        "D:\\Personal Project\\rtk",
        "run",
        "rtk-mcp"
      ]
    }
  }
}
```

---

## Architecture Details

- **Token Estimator**: The project uses custom token estimation logic in `src/pyrtk/core/utils.py` to calculate raw/filtered context sizes and log the savings ratio.
- **MemCore Tracking Daemon**: Commands run under `rtk_run_command` trigger background daemon threads to report telemetry to a local MemCore SQLite logger on port `3111` (or `MEMCORE_PORT` env override).
- **Windows Shell Parsing**: The MCP command parser uses `shlex.split` tuned for Windows compatibility, preserving quoted arguments and handling backslashes correctly.
