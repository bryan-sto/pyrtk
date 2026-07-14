# pyrtk — Token Compression Rules

pyrtk is a local MCP server that compresses shell command output before it
enters the agent context window. It saves 60–95% of tokens on common dev
commands by filtering noise and keeping only signal.

## Core Rule

ALWAYS use `rtk_run_command` instead of running shell commands directly.
This applies to every command listed below.

## Supported Commands — Use rtk_run_command for All of These

| Command | Example |
|---|---|
| git | `rtk_run_command("git status", cwd="/path/to/project")` |
| pytest | `rtk_run_command("pytest tests/ -x")` |
| ruff | `rtk_run_command("ruff check src/")` |
| grep / rg | `rtk_run_command("rg 'pattern' src/")` |
| find | `rtk_run_command("find . -name '*.py'")` |
| pip / uv pip | `rtk_run_command("uv pip list")` |
| docker | `rtk_run_command("docker ps")` |
| ls | `rtk_run_command("ls .", cwd="/path/to/dir")` |
| read (source file) | `rtk_run_command("read src/main.py aggressive")` |
| err (any command) | `rtk_run_command("err cargo build")` |
| test (any runner) | `rtk_run_command("test go test ./...")` |

## Unsupported Commands

Pass through `rtk_run_command` anyway — it returns raw output and still
logs the token usage so `rtk_discover` can surface it as a coverage gap.

## Utility Tools

- `rtk_gain()` — check token savings for this session
- `rtk_passthrough("cmd")` — bypass filtering when you need full raw output
- `rtk_discover(since_hours=24)` — find commands that bypassed pyrtk
- `rtk_check_background(handle_id)` — check status and tail logs of background tasks
- `rtk_retrieve(ref)` — recover original uncompressed json/text from CCR cache

## Reading Source Files

Prefer `rtk_run_command("read <file>")` over reading files directly.
Use `aggressive` level when you only need function signatures:
`rtk_run_command("read src/main.py aggressive")`

## CacheAligner (Prefix Stabilization)

When constructing context prompts or injecting tool results:
1. Put static blocks (rules, schemas, tool descriptions) first. Make them byte-identical across calls.
2. Put dynamic content (e.g. tool output, file contents) after the static prefix. Never interleave it.
3. Keep timestamps, session IDs, and transient data at the very end.
This ensures optimal prefix caching by the LLM.

## Notes

- All commands respect the `cwd` parameter — always pass it for project commands
- Exit codes are preserved — a failed command still fails after filtering
- `MEMCORE_PORT` env var controls which MemCore instance is used (default: 3111)
