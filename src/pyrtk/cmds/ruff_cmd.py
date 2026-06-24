# src/pyrtk/cmds/ruff_cmd.py
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from collections import defaultdict

from ..core.utils import execute_command, strip_ansi
from ..tracker import track

logger = logging.getLogger(__name__)

_MAX_VIOLATIONS = int(os.getenv("RTK_MAX_VIOLATIONS", "20"))
_MAX_PER_RULE = int(os.getenv("RTK_MAX_PER_RULE", "3"))


def run(args: list[str], verbose: bool = False) -> None:
    """Proxy ruff — violations grouped by rule code via JSON output.

    Subcommands handled: check (default), format.
    Falls back to text parsing if JSON mode fails.
    """
    sub = args[0] if args else "check"
    cmd = ["ruff"] + args

    t0 = time.time()
    stdout, stderr, code = execute_command(cmd)
    exec_ms = int((time.time() - t0) * 1000)

    raw = strip_ansi(stdout + stderr)

    if sub == "check":
        filtered = _filter_check_json(args) or _filter_check_text(raw)
    elif sub == "format":
        filtered = _filter_format(raw)
    else:
        filtered = raw

    if verbose:
        pct = int(max(0, len(raw) - len(filtered)) / max(len(raw), 1) * 100)
        print(f"[pyrtk] ruff {sub} → {pct}% saved", file=sys.stderr)

    print(filtered)
    track(" ".join(cmd), f"pyrtk {' '.join(cmd)}", raw, filtered, exec_ms)

    if code != 0:
        raise SystemExit(code)


def _filter_check_json(args: list[str]) -> str | None:
    """Re-run ruff check with --output-format json for reliable structured parsing."""
    clean_args = [a for a in args[1:] if not a.startswith("--output-format")]
    json_cmd = ["ruff", "check", "--output-format", "json"] + clean_args

    stdout, _, _ = execute_command(json_cmd)

    try:
        violations: list[dict] = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning("ruff JSON parse failed — falling back to text: %s", stdout[:80])
        return None

    if not violations:
        return "ruff: no violations ✓"

    # Group by rule code, sorted by frequency descending
    by_rule: dict[str, list[str]] = defaultdict(list)
    for v in violations:
        rule = v.get("code") or "?"
        filename = v.get("filename", "?")
        row = v.get("location", {}).get("row", "?")
        msg = v.get("message", "")
        by_rule[rule].append(f"  {filename}:{row} {msg}")

    total = len(violations)
    lines = [f"ruff: {total} violation(s) — {len(by_rule)} rule(s)\n"]
    shown = 0

    for rule, instances in sorted(by_rule.items(), key=lambda x: -len(x[1])):
        lines.append(f"{rule} ({len(instances)}×)")
        for inst in instances[:_MAX_PER_RULE]:
            lines.append(inst)
            shown += 1
        if len(instances) > _MAX_PER_RULE:
            lines.append(f"  ... +{len(instances) - _MAX_PER_RULE} more")
        if shown >= _MAX_VIOLATIONS:
            remaining = total - shown
            if remaining > 0:
                lines.append(f"\n[{remaining} violations omitted — run ruff check directly]")
            break

    return "\n".join(lines)


def _filter_check_text(raw: str) -> str:
    """Fallback text parser — group violations by file."""
    _LINE_RE = re.compile(r"^(.+?):(\d+):\d+:\s+([A-Z]\d+)\s+(.+)$")
    by_file: dict[str, int] = defaultdict(int)

    for line in raw.splitlines():
        m = _LINE_RE.match(line)
        if m:
            by_file[m.group(1)] += 1

    if not by_file:
        return raw[:400] if raw.strip() else "ruff: no violations ✓"

    total = sum(by_file.values())
    result = [f"ruff: {total} violation(s) across {len(by_file)} file(s)"]
    for f, count in sorted(by_file.items(), key=lambda x: -x[1])[:15]:
        result.append(f"  {f}: {count}")
    return "\n".join(result)


def _filter_format(raw: str) -> str:
    """Extract summary line from ruff format output."""
    for line in raw.splitlines():
        s = line.strip()
        if s and any(w in s for w in ("reformatted", "unchanged", "file", "error")):
            return s
    return raw[:200]
