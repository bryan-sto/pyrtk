# RTK (Rust Token Killer) — Deep Research

> **Version researched:** v0.42.4 (latest as of June 2026)  
> **Repo:** https://github.com/rtk-ai/rtk  
> **License:** Apache 2.0  
> **Stars:** 64k+ | **Forks:** 4k+  

---

## Table of Contents

1. [What Is RTK?](#1-what-is-rtk)
2. [The Core Problem It Solves](#2-the-core-problem-it-solves)
3. [System Architecture](#3-system-architecture)
4. [Command Lifecycle (Six Phases)](#4-command-lifecycle-six-phases)
5. [Hook System](#5-hook-system)
6. [The 12 Filtering Strategies](#6-the-12-filtering-strategies)
7. [Module Ecosystem Coverage](#7-module-ecosystem-coverage)
8. [Token Tracking & Analytics](#8-token-tracking--analytics)
9. [Configuration System](#9-configuration-system)
10. [Supported AI Tools](#10-supported-ai-tools)
11. [Performance Characteristics](#11-performance-characteristics)
12. [Known Limitations & Security Notes](#12-known-limitations--security-notes)
13. [Suggested Local Stack (Python/uv)](#13-suggested-local-stack-pythonuv)

---

## 1. What Is RTK?

RTK (**Rust Token Killer**) is a CLI proxy — a thin layer that sits between your AI coding agent (Claude Code, Cursor, Gemini CLI, `agy`, etc.) and the shell. When the agent runs a command like `git status`, RTK intercepts the raw output, compresses it using one of 12 smart filtering strategies, and returns only the signal — stripping the noise.

The result: **60–90% fewer tokens** consumed by routine dev commands, with under 10ms overhead.

```
Without RTK:
  Agent ──git status──> shell ──> git
    ^                               |
    |       ~2,000 tokens (raw)     |
    +───────────────────────────────+

With RTK:
  Agent ──git status──> RTK ──> git
    ^                    |         |
    |   ~200 tokens      | filter  |
    +─── (filtered) ─────+─────────+
```

It is written in **Rust** (92.8% of the codebase), ships as a **single binary** with zero runtime dependencies, and has 40+ command modules covering git, test runners, linters, package managers, Docker/Kubernetes, AWS, and more.

---

## 2. The Core Problem It Solves

A typical 30-minute Claude Code session burns ~118,000 tokens on shell command output alone:

| Operation          | Frequency | Standard Tokens | RTK Tokens | Savings |
|--------------------|-----------|-----------------|------------|---------|
| `ls` / `tree`      | 10×       | 2,000           | 400        | −80%    |
| `cat` / `read`     | 20×       | 40,000          | 12,000     | −70%    |
| `grep` / `rg`      | 8×        | 16,000          | 3,200      | −80%    |
| `git status`       | 10×       | 3,000           | 600        | −80%    |
| `git diff`         | 5×        | 10,000          | 2,500      | −75%    |
| `cargo test`       | 5×        | 25,000          | 2,500      | −90%    |
| `pytest`           | 4×        | 8,000           | 800        | −90%    |
| `docker ps`        | 3×        | 900             | 180        | −80%    |
| **Total**          |           | **~118,000**    | **~23,900**| **−80%**|

The bigger argument: even with 200K context windows, **filling them with verbose git log output degrades LLM reasoning quality**. RTK doesn't just save money — it keeps the context window clean so the model can focus on your actual code.

---

## 3. System Architecture

RTK follows a **proxy pattern** with five components:

```
┌─────────────────────────────────────────────────────────────────┐
│                     RTK System Components                       │
└─────────────────────────────────────────────────────────────────┘

  ┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
  │  AI Agent    │────>│  Shell Hook  │────>│  RTK Binary      │
  │ (Claude Code │     │ (PreToolUse) │     │ (Rust, ~4.1MB)   │
  │  Cursor, agy)│     │ rewrites cmd │     │                  │
  └──────────────┘     └──────────────┘     └────────┬─────────┘
                                                      │
                              ┌───────────────────────┤
                              │                       │
                    ┌─────────▼──────┐     ┌──────────▼────────┐
                    │ Filter Engine  │     │  SQLite Tracker    │
                    │ 12 strategies  │     │ ~/.local/share/    │
                    │ 40+ modules    │     │ rtk/history.db     │
                    └────────────────┘     └───────────────────-┘
```

**Source layout (Rust):**

```
src/
├── main.rs                  # Clap CLI entry + Commands enum
├── cmds/
│   ├── git/                 # git, gh CLI (7 operations)
│   ├── js/                  # lint, tsc, next, prettier, vitest, playwright, prisma, pnpm (8)
│   ├── python/              # ruff, pytest, pip (3)
│   ├── go/                  # go test/build/vet, golangci-lint (2)
│   ├── ruby/                # rake, rspec, rubocop, bundle (4)
│   ├── rust/                # cargo test/build/clippy, err, runner (5)
│   ├── dotnet/              # dotnet build/test, binlog (3)
│   ├── cloud/               # aws, docker, kubectl, curl, wget, psql (6+)
│   └── system/              # ls, tree, read, grep, find, json, log, env, deps (9+)
├── core/
│   ├── filter.rs            # Code filtering (None/Minimal/Aggressive)
│   ├── tracking.rs          # SQLite token tracking
│   ├── tee.rs               # Failure output recovery
│   ├── config.rs            # Config file loading
│   ├── toml_filter.rs       # TOML-driven custom filters
│   ├── utils.rs             # truncate, strip_ansi, execute_command, ruby_exec
│   └── telemetry.rs         # Opt-in analytics
├── hooks/
│   ├── init.rs              # rtk init workflow
│   ├── rewrite.rs           # rtk rewrite (hook shell script)
│   ├── verify.rs            # hook integrity check
│   └── trust.rs             # TOML filter SHA-256 verification
└── analytics/
    ├── gain.rs              # rtk gain reporting
    ├── session_cmd.rs       # per-session analytics
    └── ccusage.rs           # Claude Code economics
```

**Total: 64 modules** — 42 command modules + 22 infrastructure modules.

---

## 4. Command Lifecycle (Six Phases)

Every RTK command goes through exactly six phases:

```
Phase 1: PARSE
  Clap parser extracts command, args, flags (-v, -u)

Phase 2: ROUTE
  main.rs dispatches to the right module in src/cmds/

Phase 3: EXECUTE
  std::process::Command spawns the real tool
  Captures stdout + stderr + exit code

Phase 4: FILTER
  Module-specific strategy applied to raw output
  Example: git log → Stats Extraction → "5 commits, +142/−89"

Phase 5: PRINT
  Filtered output printed to stdout
  Debug info to stderr (if -v/-vv/-vvv)

Phase 6: TRACK
  SQLite INSERT: input_tokens, output_tokens, savings_pct, exec_time_ms
  Token estimate: len(text) / 4  (GPT-style heuristic)
  Auto-cleanup: DELETE records older than 90 days
```

**Verbosity levels:**

| Flag    | Behavior                             |
|---------|--------------------------------------|
| (none)  | Compact output only                  |
| `-v`    | + Debug messages                     |
| `-vv`   | + Command being executed             |
| `-vvv`  | + Raw output before filtering        |

---

## 5. Hook System

The hook is what makes RTK **transparent** — you never have to prefix commands yourself.

### How It Works

`rtk init -g` injects a `PreToolUse` hook into Claude Code's `settings.json`. The hook intercepts every Bash tool call before it executes and rewrites it:

```
Agent issues:   git status
Hook rewrites:  rtk git status
Agent receives: compact filtered output
(Agent never sees the rewrite)
```

### Two Hook Strategies

```
Auto-Rewrite (default)              Suggest (non-intrusive)
─────────────────────               ────────────────────────
Hook intercepts command             Hook emits systemMessage hint
Rewrites before execution           Agent decides autonomously
100% adoption                       ~70-85% adoption
Zero context overhead               Minimal context overhead
```

### Hook Init Per Agent

```bash
rtk init -g                     # Claude Code / Copilot (default)
rtk init -g --gemini            # Gemini CLI
rtk init -g --codex             # Codex (OpenAI)
rtk init -g --agent cursor      # Cursor
rtk init -g --agent windsurf    # Windsurf
rtk init --agent cline          # Cline / Roo Code
rtk init --agent antigravity    # Google Antigravity (agy!)
rtk init --agent hermes         # Hermes
```

> **Note for `agy` users:** `rtk init --agent antigravity` drops `.agents/rules/antigravity-rtk-rules.md` in your repo. Works as an AGENTS.md-style rule file.

### Scope Limitation

The hook **only fires on Bash tool calls**. Claude Code's built-in `Read`, `Grep`, and `Glob` tools bypass it entirely. For full coverage you need to use shell equivalents (`cat`, `rg`, `find`) or call `rtk read`, `rtk grep`, `rtk find` explicitly.

### Windows Behavior

On native Windows (no WSL), the hook falls back to **CLAUDE.md injection mode** — RTK writes instructions into the agent's context file so it uses `rtk` prefixes manually. Full hook support requires WSL.

---

## 6. The 12 Filtering Strategies

Each command module applies one or more of these strategies:

### 1. Stats Extraction (90–99% reduction)
Aggregates counts and numeric summaries, drops line-by-line detail.  
*Used by:* `git status`, `git log`, `git diff`, `pnpm list`

```
Input: "5 files changed, 142 insertions(+), 89 deletions(-)\n..."  (500 chars)
Output: "5 commits, +142/−89"  (20 chars)
```

### 2. Error Only (60–80% reduction)
Keeps only stderr; discards stdout entirely.  
*Used by:* `rtk err <cmd>`, test failure mode

### 3. Grouping by Pattern (80–90% reduction)
Groups errors/violations by rule, file, or type with counts.  
*Used by:* `lint` (ESLint), `tsc`, `grep`, `golangci-lint`, `ruff check`

```
Input: 100 scattered ESLint errors
Output: "no-unused-vars: 23  semi: 45  eqeqeq: 12"
```

### 4. Deduplication (70–85% reduction)
Collapses repeated log lines with a count suffix.  
*Used by:* `docker logs`, `kubectl logs`, `log`

```
Input: "[ERROR] Health check failed\n" × 500 lines
Output: "[ERROR] Health check failed (×500)"
```

### 5. Structure Only (80–95% reduction)
Extracts JSON schema (keys + types), strips values.  
*Used by:* `rtk json <file>`

```
Input: {"user": {"id": 12345, "name": "Alice", "email": "..."}}
Output: {user: {id: int, name: str, email: str}}
```

### 6. Code Filtering (0–90% reduction, 3 levels)
Language-aware source code compression with three levels:
- **None** — keep everything
- **Minimal** — strip comments + whitespace (20–40%)
- **Aggressive** — strip function bodies, keep signatures only (60–90%)

*Used by:* `rtk read`, `rtk smart`  
Supports: Rust, Python, JS, TS, Go, C/C++, Java

### 7. Failure Focus (94–99% reduction)
Hides all passing tests; shows only failures with file:line.  
*Used by:* `vitest`, `playwright`, `rtk test <cmd>`, `pytest`

```
Input: 200+ lines (100 passing tests + 2 failures)
Output: "FAILED: 2/15\n  • test_auth: assertion failed\n  • test_overflow: panic"
```

### 8. Tree Compression (50–70% reduction)
Collapses flat file lists into a compact directory tree with counts.  
*Used by:* `rtk ls`

```
Input: 50 lines of ls -la
Output: src/ (8 files), Cargo.toml, README.md
```

### 9. Progress Filtering (85–95% reduction)
Strips ANSI escape codes, progress bars, live update lines; keeps final result.  
*Used by:* `wget`, `pnpm install`

### 10. JSON/Text Dual Mode (80%+)
Prefers JSON API output when the tool supports it (`--format json`), falls back to text parsing.  
*Used by:* `ruff check` (JSON), `ruff format` (text), `pip list` (JSON)

### 11. State Machine Parsing (90%+)
Tracks test lifecycle state (IDLE → TEST_START → PASSED/FAILED → SUMMARY) to extract only failures.  
*Used by:* `pytest`, `rake test`

### 12. NDJSON Streaming (90%+)
Parses newline-delimited JSON events line by line, aggregates results across interleaved packages.  
*Used by:* `go test` (which emits NDJSON with interleaved package events)

---

## 7. Module Ecosystem Coverage

### Savings by Ecosystem

| Ecosystem     | Modules  | Typical Savings | Key Commands |
|---------------|----------|-----------------|--------------|
| **Git**       | 7 ops    | 85–99%          | status, diff, log, add, commit, push, branch |
| **JS/TS**     | 8 modules| 70–99%          | lint, tsc, next, prettier, playwright, prisma, vitest, pnpm |
| **Python**    | 3 modules| 70–90%          | ruff, pytest, pip |
| **Go**        | 2 modules| 75–90%          | go test/build/vet, golangci-lint |
| **Ruby**      | 4 modules| 60–90%          | rake, rspec, rubocop, bundle |
| **.NET**      | 3 modules| 70–85%          | dotnet build/test, binlog |
| **Cloud**     | 6+ modules| 60–80%         | aws, docker, kubectl, curl, wget, psql |
| **System**    | 9+ modules| 50–90%         | ls, tree, read, grep, find, json, log, env, deps |
| **Rust**      | 5 modules| 60–99%          | cargo test/build/clippy, err |

### Notable Command Behaviors

**Git:**
```bash
rtk git push     # "ok main" (was 15 lines)
rtk git status   # compact changed/untracked list (was 30+ lines)
rtk git log -n 5 # "5 commits, +142/−89 ✓"
```

**Python:**
```bash
rtk pytest       # failures only; state machine parser; 90%+ savings
rtk ruff check   # JSON API; grouped by rule; 80%+ savings
rtk pip list     # compact table; auto-detects uv if present
```

**Test runners (generic):**
```bash
rtk test <any cmd>  # wraps any test runner; failures only
rtk err <any cmd>   # wraps any command; stderr/errors only
```

**Tee failure recovery:**  
When a command fails, RTK saves the full unfiltered output to `~/.local/share/rtk/tee/`. The compressed output includes a path reference so the agent can read it if needed:
```
FAILED: 2/15 tests
[full output: ~/.local/share/rtk/tee/1707753600_cargo_test.log]
```

---

## 8. Token Tracking & Analytics

RTK uses **SQLite** (`~/.local/share/rtk/history.db`) to track every command.

### Schema

```sql
CREATE TABLE commands (
  id            INTEGER PRIMARY KEY,
  timestamp     TEXT NOT NULL,         -- RFC3339
  original_cmd  TEXT NOT NULL,         -- "git log --oneline -5"
  rtk_cmd       TEXT NOT NULL,         -- "rtk git log --oneline -5"
  input_tokens  INTEGER NOT NULL,      -- len(raw) / 4
  output_tokens INTEGER NOT NULL,      -- len(filtered) / 4
  saved_tokens  INTEGER NOT NULL,
  savings_pct   REAL NOT NULL,
  exec_time_ms  INTEGER DEFAULT 0
);
```

Token estimation heuristic: `ceil(len(text) / 4)` — matches GPT-style tokenization closely enough.

Auto-cleanup: records older than 90 days are deleted on each INSERT.

### Analytics Commands

```bash
rtk gain                   # 90-day summary (commands, avg savings %, total tokens saved)
rtk gain --graph           # ASCII graph, last 30 days
rtk gain --history         # recent command history
rtk gain --daily           # day-by-day breakdown
rtk gain --all --format json  # JSON export

rtk discover               # find commands NOT going through RTK (missed savings)
rtk discover --all --since 7  # last 7 days, all projects

rtk session                # RTK adoption rate in recent sessions
```

Real-world output from a happy developer after a few weeks of daily use:
> 15,720 commands processed · 138M tokens saved · 88.9% efficiency

---

## 9. Configuration System

### Config File: `~/.config/rtk/config.toml`

```toml
[hooks]
exclude_commands = ["curl", "playwright"]  # skip rewrite for these

[tee]
enabled = true          # save raw output on failure (default: true)
mode = "failures"       # "failures" | "always" | "never"
```

### TOML Custom Filters

You can write per-command filter rules in `~/.config/rtk/filters.toml` or project-local `.rtk/filters.toml`. The project-local file requires SHA-256 verification (`rtk verify`) before it's trusted — a security measure since RTK sits in the LLM's output pipeline and a malicious filter could suppress security scanner output.

### Initialization

```bash
rtk init -g                 # Install hook + RTK.md (recommended)
rtk init -g --hook-only     # Hook only, no RTK.md
rtk init --show             # Verify installation
rtk init -g --uninstall     # Remove everything
```

---

## 10. Supported AI Tools

| Tool              | Install                          | Method                              |
|-------------------|----------------------------------|-------------------------------------|
| Claude Code       | `rtk init -g`                    | PreToolUse hook (bash)              |
| GitHub Copilot    | `rtk init -g --copilot`          | PreToolUse hook                     |
| Cursor            | `rtk init -g --agent cursor`     | preToolUse hook (hooks.json)        |
| Gemini CLI        | `rtk init -g --gemini`           | BeforeTool hook                     |
| Windsurf          | `rtk init -g --agent windsurf`   | .windsurfrules                      |
| Cline / Roo Code  | `rtk init --agent cline`         | .clinerules                         |
| **Antigravity**   | `rtk init --agent antigravity`   | .agents/rules/antigravity-rtk-rules.md |
| Hermes            | `rtk init --agent hermes`        | Python plugin adapter               |
| Kilo Code         | `rtk init --agent kilocode`      | .kilocode/rules/rtk-rules.md        |
| Codex             | `rtk init -g --codex`            | AGENTS.md + RTK.md instructions     |

---

## 11. Performance Characteristics

```
Binary size:    ~4.1 MB (stripped release build)
Startup:        5–10ms (cold start)
Memory:         2–5 MB typical
Proxy overhead: 5–15ms per command

Overhead breakdown:
  Clap parsing:      2–3ms
  Command execution: 1–2ms
  Filtering:         2–8ms (varies by strategy)
  SQLite tracking:   1–3ms
```

| Command                 | Raw Time | RTK Time | Overhead |
|-------------------------|----------|----------|----------|
| `rtk git status`        | 50ms     | 58ms     | +8ms     |
| `rtk grep "pattern"`    | 133ms    | 145ms    | +12ms    |
| `rtk read file.rs`      | 10ms     | 15ms     | +5ms     |
| `rtk lint`              | 2.5s     | 2.515s   | +15ms    |
| `rtk pytest`            | 1.2s     | 1.21s    | +10ms    |

---

## 12. Known Limitations & Security Notes

**Functional Limitations:**

- Hook only fires on Bash tool calls. Native `Read`, `Grep`, `Glob` in Claude Code bypass it entirely — so if your agent leans on those, RTK's coverage is reduced.
- On Windows without WSL, no auto-rewrite hook — falls back to CLAUDE.md injection mode (manual prefix).
- Over-compression risk: some filters can be too aggressive. If you need exact file permissions, timestamps, or full stack traces, the compressed output may omit them. Use `-v` or `rtk proxy <cmd>` for raw passthrough.
- TOML filter customization has a learning curve.

**Security Notes:**

- The PreToolUse hook auto-approves rewritten commands, bypassing Claude Code's normal permission prompt.
- RTK stores full command strings (including arguments like `curl -H "Authorization: Bearer tok_..."`) in SQLite for 90 days. `rtk gain --history` can surface these in LLM context.
- Global `~/.config/rtk/filters.toml` is trusted unconditionally; project-local `.rtk/filters.toml` requires SHA-256 verification.
- Telemetry is opt-in, GDPR-compliant, and stores only anonymous aggregate data (no source code, file paths, or secrets).

**Recommended mitigations:**

```bash
rtk telemetry disable
export RTK_TELEMETRY_DISABLED=1   # add to .bashrc / .zshrc

# Exclude sensitive commands
# ~/.config/rtk/config.toml
[hooks]
exclude_commands = ["curl", "aws", "kubectl"]
```

---

## 13. Suggested Local Stack (Python + uv)

This section is a **blueprint for building your own RTK-equivalent locally**, similar in spirit to how MemCore (Node.js + SQLite + MCP) works as local infrastructure for `agy`.

### Philosophy

Just like MemCore is your local MCP memory server, an RTK-equivalent (`pyrtk`) would be a local **output compression layer** for your agy/Claude Code sessions. You own the code, extend it yourself, and it lives in your dev environment — no external dependency.

### Tech Stack

```
pyrtk/
├── Core:         Python 3.12+ with uv
├── CLI:          typer (argument parsing, like Clap in Rust)
├── Analytics:    SQLite via stdlib sqlite3 (no ORM needed)
├── Text:         re (regex), rich (colored output)
├── ANSI:         strip_ansi or manual regex
└── Integration:  AGENTS.md rule file for agy
```

### Project Init (uv)

```bash
uv init pyrtk
cd pyrtk
uv add typer rich
uv add --dev pytest ruff
```

### Project Structure

```
pyrtk/
├── pyproject.toml
├── src/
│   └── pyrtk/
│       ├── __init__.py
│       ├── main.py              # typer CLI entry point
│       ├── tracker.py           # SQLite tracking (mirrors tracking.rs)
│       ├── core/
│       │   ├── filter.py        # strip_ansi, truncate, code filtering
│       │   └── utils.py         # execute_command, detect_pm
│       └── cmds/
│           ├── git.py           # git status/log/diff/push
│           ├── pytest_cmd.py    # state machine parser
│           ├── pip_cmd.py       # JSON-first parsing
│           ├── docker_cmd.py    # docker ps/logs dedup
│           ├── ls_cmd.py        # tree compression
│           └── grep_cmd.py      # group by file
├── agents/
│   └── pyrtk-rules.md          # AGENTS.md rule file for agy
└── tests/
    └── test_git.py
```

### Core Execution Pattern

```python
# src/pyrtk/core/utils.py
import subprocess, re

def execute_command(cmd: list[str]) -> tuple[str, str, int]:
    """Run a command and return (stdout, stderr, exit_code)."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
```

### Core Filters

```python
# src/pyrtk/core/filter.py
import re
import json

def dedup(text: str) -> str:
    """Collapses consecutive repeating log lines and adds count suffix."""
    lines = text.splitlines()
    if not lines:
        return ""
    result = []
    current_line = lines[0]
    count = 1
    for line in lines[1:]:
        if line == current_line:
            count += 1
        else:
            if count > 1:
                result.append(f"{current_line} (×{count})")
            else:
                result.append(current_line)
            current_line = line
            count = 1
    if count > 1:
        result.append(f"{current_line} (×{count})")
    else:
        result.append(current_line)
    return "\n".join(result)

def structure_only(json_str: str) -> str:
    """Parses JSON, replaces primitive values with type names, preserves keys."""
    try:
        data = json.loads(json_str)
        def convert(val):
            if isinstance(val, dict):
                return {k: convert(v) for k, v in val.items()}
            elif isinstance(val, list):
                if not val:
                    return []
                return [convert(val[0])] # show structure of first item
            else:
                return type(val).__name__
        return json.dumps(convert(data), indent=2)
    except json.JSONDecodeError:
        return json_str

def dual_mode_parse(raw_output: str, fallback_parser) -> str:
    """Tries parsing raw output as JSON, formats cleanly. Fallback if not valid JSON."""
    try:
        # Check if output begins with JSON markers
        stripped = raw_output.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
            parsed = json.loads(stripped)
            return json.dumps(parsed, separators=(',', ':'))
    except json.JSONDecodeError:
        pass
    return fallback_parser(raw_output)
```

### Tracker (SQLite, mirrors RTK's tracking.rs)

```python
# src/pyrtk/tracker.py
import sqlite3, datetime
from pathlib import Path

DB_PATH = Path.home() / ".local" / "share" / "pyrtk" / "history.db"

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS commands (
                id           INTEGER PRIMARY KEY,
                timestamp    TEXT NOT NULL,
                original_cmd TEXT NOT NULL,
                rtk_cmd      TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                saved_tokens INTEGER NOT NULL,
                savings_pct  REAL NOT NULL,
                exec_time_ms INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            DELETE FROM commands
            WHERE timestamp < datetime('now', '-90 days')
        """)

def track(original: str, rtk_cmd: str, raw: str, filtered: str, exec_ms: int):
    inp = len(raw) // 4
    out = len(filtered) // 4
    saved = inp - out
    pct = (saved / inp * 100) if inp > 0 else 0.0
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO commands
            (timestamp, original_cmd, rtk_cmd, input_tokens, output_tokens, saved_tokens, savings_pct, exec_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (datetime.datetime.utcnow().isoformat(), original, rtk_cmd, inp, out, saved, pct, exec_ms))
```

### Example Command Module (git)

```python
# src/pyrtk/cmds/git.py
from pyrtk.core.utils import execute_command, strip_ansi
from pyrtk.tracker import track
import time, re

def run(args: list[str], verbose: bool = False):
    cmd = ["git"] + args
    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)
    sub = args[0] if args else ""

    if sub == "status":
        filtered = _filter_status(raw)
    elif sub == "log":
        filtered = _filter_log(raw)
    elif sub in ("add", "commit", "push", "pull"):
        filtered = _filter_simple(raw, sub)
    elif sub == "diff":
        filtered = _filter_diff(raw)
    else:
        filtered = raw

    if verbose:
        print(f"[pyrtk] git {sub} → {len(filtered)}/{len(raw)} chars "
              f"({100 - len(filtered)*100//max(len(raw),1)}% saved)", flush=True)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        exit(code)

def _filter_status(raw: str) -> str:
    modified, untracked = [], []
    for line in raw.splitlines():
        if line.startswith("\tmodified:"):
            modified.append(line.strip().replace("modified:", "M"))
        elif line.startswith("\t") and "new file" not in line:
            untracked.append("?" + line.strip())
    parts = []
    if modified:
        parts.append(f"modified: {', '.join(modified)}")
    if untracked:
        parts.append(f"untracked: {len(untracked)} file(s)")
    return "\n".join(parts) if parts else "clean"

def _filter_log(raw: str) -> str:
    lines = [l for l in raw.splitlines() if re.match(r'^[0-9a-f]{6,}', l)]
    return "\n".join(lines[:10]) if lines else raw[:200]

def _filter_diff(raw: str) -> str:
    stats = [l for l in raw.splitlines() if re.match(r'^\s*\d+\s+files? changed', l)]
    return stats[0] if stats else raw[:400]

def _filter_simple(raw: str, sub: str) -> str:
    if "error" in raw.lower():
        return raw[:300]
    if sub == "push":
        branch = re.search(r'(HEAD -> |origin/)([^\s]+)', raw)
        return f"ok {branch.group(2) if branch else 'done'}"
    if sub in ("add", "commit"):
        sha = re.search(r'([0-9a-f]{7})', raw)
        return f"ok {sha.group(1) if sha else sub}"
    return "ok"
```

### Example Command Module (ls - System filter)

```python
# src/pyrtk/cmds/ls_cmd.py
from pyrtk.core.utils import execute_command
from pathlib import Path

def run(args: list[str], verbose: bool = False):
    target = Path(args[0]) if args else Path(".")
    if not target.exists():
        print(f"Path not found: {target}")
        return
    if target.is_file():
        print(f"{target.name} ({target.stat().st_size}B)")
        return
    dirs = []
    files_count = 0
    for item in target.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            subfiles = sum(1 for _ in item.glob('*') if _.is_file())
            dirs.append(f"{item.name}/ ({subfiles} files)")
        elif item.is_file() and not item.name.startswith('.'):
            files_count += 1
    output = []
    if dirs:
        output.extend(dirs)
    if files_count:
        output.append(f"files: {files_count} file(s) in root")
    print("\n".join(output) if output else "empty directory")
```

### Example Command Module (docker - Cloud filter)

```python
# src/pyrtk/cmds/docker_cmd.py
from pyrtk.core.utils import execute_command, strip_ansi
from pyrtk.core.filter import dedup
import re

def run(args: list[str], verbose: bool = False):
    cmd = ["docker"] + args
    stdout, stderr, code = execute_command(cmd)
    raw = strip_ansi(stdout + stderr)
    sub = args[0] if args else ""
    if sub == "ps":
        filtered = _filter_ps(raw)
    elif sub == "logs":
        filtered = dedup(raw)
    else:
        filtered = raw
    print(filtered)

def _filter_ps(raw: str) -> str:
    lines = raw.splitlines()
    if len(lines) <= 1:
        return "no containers running"
    result = ["CONTAINER ID | IMAGE | STATUS | NAMES"]
    for line in lines[1:]:
        parts = re.split(r'\s{2,}', line.strip())
        if len(parts) >= 6:
            result.append(f"{parts[0]} | {parts[1]} | {parts[4]} | {parts[-1]}")
    return "\n".join(result)
```

### CLI Entry Point (typer)

```python
# src/pyrtk/main.py
import typer
from pyrtk.tracker import init_db
from pyrtk import cmds

app = typer.Typer(help="pyrtk — local RTK-equivalent, Python edition")

@app.command()
def git(args: list[str] = typer.Argument(...), verbose: bool = typer.Option(False, "-v")):
    """Proxy git with compact output."""
    cmds.git.run(args, verbose)

@app.command()
def pytest(args: list[str] = typer.Argument(default=[]), verbose: bool = typer.Option(False, "-v")):
    """Run pytest; show failures only."""
    cmds.pytest_cmd.run(args, verbose)

@app.command()
def ls(args: list[str] = typer.Argument(default=[]), verbose: bool = typer.Option(False, "-v")):
    """Compress file listing."""
    cmds.ls_cmd.run(args, verbose)

@app.command()
def docker(args: list[str] = typer.Argument(...), verbose: bool = typer.Option(False, "-v")):
    """Proxy docker command."""
    cmds.docker_cmd.run(args, verbose)

@app.command()
def gain():
    """Show token savings report."""
    from pyrtk.tracker import report
    report()

@app.callback()
def init_callback():
    init_db()

if __name__ == "__main__":
    app()
```

### agy Integration (AGENTS.md rule)

```markdown
<!-- agents/pyrtk-rules.md -->
# pyrtk — Token Compression Rules

When running shell commands, prefer pyrtk wrappers to reduce token usage:

- `pyrtk git status` instead of `git status`
- `pyrtk git log` instead of `git log --oneline`
- `pyrtk git diff` instead of `git diff`
- `pyrtk pytest` instead of `pytest` or `python -m pytest`
- `pyrtk docker ps` instead of `docker ps`
- `pyrtk ls .` instead of `ls -la`

All pyrtk commands preserve exit codes. On failure, full output is available.
Use `pyrtk gain` to see token savings for this session.
```

Place this at `.agents/rules/pyrtk-rules.md` in each project repo, or reference it from your global `~/.gemini/GEMINI.md`.

### Analytics (rtk gain equivalent)

```python
# in tracker.py
def report():
    from rich.table import Table
    from rich.console import Console
    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT COUNT(*), SUM(saved_tokens), AVG(savings_pct)
            FROM commands
            WHERE timestamp > datetime('now', '-90 days')
        """).fetchone()

    console = Console()
    table = Table(title="pyrtk Token Savings (90 days)")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Commands processed", str(row[0] or 0))
    table.add_row("Total tokens saved", f"{row[1] or 0:,}")
    table.add_row("Average savings", f"{row[2] or 0:.1f}%")
    console.print(table)
```

### Windows Notes (your setup)

Since you're on Windows:

- Shell hook won't auto-rewrite unless you're in WSL
- Instead: use the `pyrtk-rules.md` AGENTS.md approach — add it to `AGENT_MEMORY.md` or as a repo-local AGENTS.md rule so `agy` uses `pyrtk` prefixes manually
- For PowerShell, you can add an alias: `Set-Alias -Name rg -Value pyrtk` or use a `rtk.ps1` wrapper script

### Build Order Recommendation

Start with the commands you use most in your `agy` sessions:

1. **Week 1:** `pyrtk git status/log/diff/push` — highest ROI, simple to implement
2. **Week 2:** `pyrtk pytest` — state machine parser, real token savings on your Python projects
3. **Week 3:** `pyrtk docker ps/logs` + `pyrtk ls` — dedup + tree compression
4. **Week 4:** `pyrtk gain` analytics + agy rule integration + PowerShell wrapper

Each module is ~50–100 lines of Python. Week 1 alone will save the majority of your tokens.

---

## 14. Option A: MemCore Auto-Capture Integration

Unify client logger (`pyrtk`) with local MemCore server (`D:/Personal Project/am`) to auto-track without local database files.

### DB Schema (MemCore `db.sqlite`)

Add table on startup:

```sql
CREATE TABLE IF NOT EXISTS command_logs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp    TEXT NOT NULL,
  project      TEXT NOT NULL,
  command      TEXT NOT NULL,
  input_t      INTEGER NOT NULL, -- original tokens
  output_t     INTEGER NOT NULL, -- filtered tokens
  saved_t      INTEGER NOT NULL,
  pct          REAL NOT NULL,
  exec_ms      INTEGER NOT NULL
);
```

### MemCore HTTP API (`index.js`)

* `POST /agentmemory/command/log`: Receives metrics -> insert into `command_logs` DB table.
* `GET /agentmemory/gain`: Aggregate stats (total saved, avg %, daily history) -> return JSON.

### Client Logger Flow (`pyrtk`)

1. Exec command.
2. Filter stdout.
3. Compute tokens.
4. HTTP `POST` metrics to `http://localhost:3111/agentmemory/command/log`.
5. Print filtered stdout.

### Dashboard UI (`viewer.html`)

Add "Token Savings" tab:
* Metric cards: Total saved, average efficiency %, execution count.
* Charts: Line chart for daily savings over time.


## 15. Other Improvements for Local Version

1. **Smart Caching:** Cache read/ls output based on file modification times (`mtime`) or `git status`. Skip redundant command runs if files unchanged.
2. **Context-Aware Levels:** Automatically adjust filtering severity (None/Minimal/Aggressive) based on remaining token space in agent context.
3. **Autofix Interceptor:** Auto-apply suggested linter rules (e.g., `eslint --fix` or `ruff --fix`) if command returns errors.
4. **Interactive Prompt Prevention:** Detect commands prompting for input (Y/N, passwords). Kill early or notify agent to prevent terminal freezes.
5. **Debug Recovery Helper:** Add `pyrtk recover <cmd_id>` tool to instantly fetch full unfiltered logs from `~/.local/share/rtk/tee/` on command failure.

## 16. `pyrtk` MCP Server Plan (Auto-Capture)

Implement `pyrtk` as a Python MCP server to auto-capture and filter agent commands.

### Workflow

```
Agent -> Call MCP `rtk_run_command` -> MCP Exec -> Apply Filter -> HTTP Log to MemCore -> Return Compressed Output
```

### Server Setup (Python)

Uses lightweight `mcp` Python SDK:

```python
from mcp.server.fastmcp import FastMCP
import subprocess
import requests

mcp = FastMCP("pyrtk")

@mcp.tool()
def rtk_run_command(command: str, cwd: str = ".") -> str:
    """Run shell command with auto token compression and logging."""
    # 1. Parse command and execute
    t0 = time.time()
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, cwd=cwd
    )
    exec_ms = int((time.time() - t0) * 1000)
    
    # 2. Filter output
    raw_output = result.stdout + result.stderr
    filtered_output = apply_rtk_filters(command, raw_output)
    
    # 3. Log to MemCore HTTP API
    log_payload = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "project": get_project_name(cwd),
        "command": command,
        "input_t": estimate_tokens(raw_output),
        "output_t": estimate_tokens(filtered_output),
        "saved_t": estimate_tokens(raw_output) - estimate_tokens(filtered_output),
        "pct": calculate_saved_pct(raw_output, filtered_output),
        "exec_ms": exec_ms
    }
    try:
        requests.post("http://localhost:3111/agentmemory/command/log", json=log_payload, timeout=2)
    except requests.exceptions.RequestException:
        pass # MemCore server offline fallback

    # 4. Return to agent
    return filtered_output
```

### Agent Integration Rule (`.agents/rules/rtk.md`)

Inject instructions to steer agent toward the MCP tool:

```markdown
# Token Compression Rule

When executing shell commands:
- ALWAYS use `pyrtk`'s `rtk_run_command` tool instead of the default `run_command` or terminal tool.
- This automatically logs statistics to MemCore and reduces context size by 60-90%.
```

---

*Generated from rtk-ai/rtk v0.42.4 — ARCHITECTURE.md, README.md, DeepWiki analysis, and community documentation.*