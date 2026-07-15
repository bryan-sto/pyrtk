# tests/test_new_modules.py
from __future__ import annotations

import pytest

from src.pyrtk.core.filter import code_filter, FilterLevel, structure_only, dedup
from src.pyrtk.cmds.grep_cmd import _filter_grep
from src.pyrtk.cmds.find_cmd import _filter_find
from src.pyrtk.cmds.err_cmd import _filter_errors
from src.pyrtk.cmds.test_cmd import _filter_test_output
from src.pyrtk.cmds.pip_cmd import _filter_list, _filter_show


# ── structure_only ──────────────────────────────────────────────────────────

def test_structure_only_null():
    out = structure_only('{"deleted_at": null}')
    assert '"null"' in out
    assert "NoneType" not in out


def test_structure_only_depth_limit():
    # 15-deep nesting should not RecursionError
    deep = '{"a":' * 15 + '"x"' + '}' * 15
    out = structure_only(deep)
    assert "..." in out


def test_structure_only_list():
    out = structure_only('[1, 2, 3]')
    assert '"int"' in out


# ── code_filter ─────────────────────────────────────────────────────────────

def test_code_filter_none_passthrough():
    content = "# comment\ndef foo(): pass"
    assert code_filter(content, "python", FilterLevel.NONE) == content


def test_code_filter_minimal_strips_comments():
    content = "# this is a comment\ndef foo():\n    pass"
    out = code_filter(content, "python", FilterLevel.MINIMAL)
    assert "# this is a comment" not in out
    assert "def foo" in out


def test_code_filter_unknown_language_passthrough():
    content = "some content"
    assert code_filter(content, "unknown", FilterLevel.AGGRESSIVE) == content


def test_code_filter_aggressive_python_keeps_signature():
    content = "def my_func(x: int) -> str:\n    return str(x)\n"
    out = code_filter(content, "python", FilterLevel.AGGRESSIVE)
    assert "def my_func" in out
    assert "..." in out
    assert "return str(x)" not in out


def test_code_filter_aggressive_python_keeps_keeps_imports():
    content = "import os\nfrom pathlib import Path\n\ndef foo(): pass\n"
    out = code_filter(content, "python", FilterLevel.AGGRESSIVE)
    assert "import os" in out
    assert "from pathlib" in out


# ── grep_cmd ─────────────────────────────────────────────────────────────────

def test_filter_grep_empty():
    assert _filter_grep("") == "no matches"


def test_filter_grep_groups_by_file():
    raw = "src/a.py:1:match one\nsrc/a.py:2:match two\nsrc/b.py:1:other match"
    out = _filter_grep(raw)
    assert "src/a.py: 2" in out
    assert "src/b.py: 1" in out


def test_filter_grep_single_file_mode():
    raw = "match one\nmatch two\nmatch three"
    out = _filter_grep(raw)
    assert "3 match" in out


# ── find_cmd ─────────────────────────────────────────────────────────────────

def test_filter_find_empty():
    assert _filter_find("") == "no results"


def test_filter_find_small_result_passthrough():
    raw = "./a\n./b\n./c"
    assert _filter_find(raw) == raw


def test_filter_find_groups_by_dir():
    raw = "\n".join(f"./src/file{i}.py" for i in range(20))
    out = _filter_find(raw)
    assert "20 result" in out
    assert "src: 20 file(s)" in out or "./src: 20 file(s)" in out


# ── err_cmd ──────────────────────────────────────────────────────────────────

def test_filter_errors_returns_stderr():
    out = _filter_errors("normal output", "something went wrong")
    assert "something went wrong" in out
    assert "normal output" not in out


def test_filter_errors_captures_error_lines_from_stdout():
    out = _filter_errors("Error: file not found\nNormal line\nFailed to load", "")
    assert "Error: file not found" in out
    assert "Failed to load" in out
    assert "Normal line" not in out


def test_filter_errors_deduplicates():
    stderr = "connection error\nconnection error\nconnection error"
    out = _filter_errors("", stderr)
    assert out.count("connection error") == 1


# ── test_cmd ─────────────────────────────────────────────────────────────────

def test_filter_test_all_passed_exit_0():
    raw = "...\n3 passed in 0.5s"
    out = _filter_test_output(raw, 0)
    assert "passed" in out


def test_filter_test_extracts_pytest_failures():
    raw = (
        "..F\n"
        "=== FAILURES ===\n"
        "____ test_foo ____\n"
        "    assert 1 == 2\n"
        "AssertionError\n"
        "=== short test summary ===\n"
        "FAILED test_foo.py::test_foo\n"
        "1 failed in 0.8s"
    )
    out = _filter_test_output(raw, 1)
    assert "FAILURES" in out
    assert "assert 1 == 2" in out
    assert "1 failed" in out
    assert "..F" not in out  # progress dots stripped


def test_filter_test_collection_error_not_all_passed():
    raw = "ImportError while collecting tests\ncollected 0 items / 1 error"
    out = _filter_test_output(raw, 2)
    assert "all tests passed" not in out
    assert "ImportError" in out


# ── pip_cmd ──────────────────────────────────────────────────────────────────

def test_filter_pip_list_valid_json():
    raw = '[{"name": "requests", "version": "2.31.0"}, {"name": "typer", "version": "0.9.0"}]'
    out = _filter_list(raw)
    assert "2 package" in out
    assert "requests" in out
    assert "typer" in out


def test_filter_pip_list_empty():
    assert _filter_list("[]") == "no packages installed"


def test_filter_pip_list_invalid_json():
    out = _filter_list("not json")
    assert len(out) <= 404  # falls back to raw[:400]


def test_filter_pip_show_keeps_key_fields():
    raw = (
        "Name: requests\n"
        "Version: 2.31.0\n"
        "Summary: HTTP library\n"
        "Home-page: https://requests.readthedocs.io\n"
        "Author: Kenneth Reitz\n"
        "License: Apache 2.0\n"
        "Requires: certifi, urllib3\n"
        "Required-by: httpx\n"
    )
    out = _filter_show(raw)
    assert "Name: requests" in out
    assert "Summary: HTTP library" in out
    assert "Author: Kenneth Reitz" not in out   # not in _SHOW_KEEP
    assert "License: Apache 2.0" not in out     # not in _SHOW_KEEP


# ── MemCore down fallback test ────────────────────────────────────────────────

def test_track_memcore_down(monkeypatch):
    monkeypatch.setenv("MEMCORE_PORT", "9")  # nothing running on port 9
    from src.pyrtk.tracker import track
    # Should not raise exception
    track("git status", "pyrtk git status", "raw", "filtered", 10)


# ── Background Process & Registry Tests ───────────────────────────────────────

def test_registry_basic(tmp_path):
    from src.pyrtk.registry import ProcessRegistry
    import subprocess
    import sys

    reg = ProcessRegistry(db_dir=tmp_path)
    
    # Start a dummy process
    proc = subprocess.Popen([sys.executable, "-c", "print('hello')"], stdout=subprocess.PIPE)
    proc.wait()

    handle_id = reg.register(proc, ["dummy"], "stdout.log", "stderr.log")
    assert handle_id is not None

    entry = reg.get(handle_id)
    assert entry.pid == proc.pid
    assert entry.cmd == ["dummy"]

    reg.update_status(handle_id, 123.45, 0)
    entry2 = reg.get(handle_id)
    assert entry2.exit_code == 0
    assert entry2.ended_at == 123.45


def test_rtk_run_background_and_check(tmp_path):
    from src.pyrtk.mcp_server import rtk_run_command, rtk_check_background
    import json
    import sys
    import time

    # Run background python sleep process
    cmd = f'"{sys.executable}" -c "import time; time.sleep(0.1); print(\'done\')"'
    res_str = rtk_run_command(cmd, cwd=str(tmp_path), background=True)
    res = json.loads(res_str)

    assert "handle_id" in res
    assert "pid" in res

    handle_id = res["handle_id"]

    # Check background status (should be alive)
    status_str = rtk_check_background(handle_id)
    status = json.loads(status_str)
    assert status["pid"] == res["pid"]
    assert status["alive"] is True

    # Wait for completion (up to 3 seconds)
    status2 = None
    for _ in range(30):
        status_str2 = rtk_check_background(handle_id)
        status2 = json.loads(status_str2)
        if not status2["alive"]:
            break
        time.sleep(0.1)

    assert status2 is not None
    assert status2["alive"] is False
    assert status2["exit_code"] == 0
    assert "done" in status2["stdout_tail"]


# ── JSON Columnar Compressor & CCR Cache Tests ───────────────────────────────

def test_ccr_store_and_retrieve(tmp_path):
    from src.pyrtk.registry import ProcessRegistry
    import time
    
    reg = ProcessRegistry(db_dir=tmp_path)
    data = {"some": "data", "list": [1, 2, 3]}
    
    ref = reg.ccr_store(data, ttl=5)
    assert ref.startswith("ccr_")
    
    retrieved = reg.ccr_retrieve(ref)
    assert retrieved == data

    # Test expiration
    ref_expired = reg.ccr_store(data, ttl=-1)
    with pytest.raises(KeyError, match="expired"):
        reg.ccr_retrieve(ref_expired)


def test_compress_json_columnar(tmp_path):
    from src.pyrtk.core.json_compress import compress_json
    from src.pyrtk.registry import registry
    
    # Temporarily redirect registry db path to tmp_path for isolation
    old_db = registry.db_path
    registry.db_path = tmp_path / "test_registry.db"
    registry._init_db()

    try:
        # Create homogeneous array of 30 dicts (oversized)
        data = [
            {"id": i, "status": "active", "tag": "test" if i % 10 == 0 else "default"}
            for i in range(30)
        ]
        
        res = compress_json(data, max_rows=10)
        compressed = res["compressed"]
        
        assert "schema" in compressed
        assert "rows" in compressed
        assert "defaults" in compressed
        
        # Dominant key "status" is "active" across 100% of rows -> not in schema, only in defaults
        assert "status" in compressed["defaults"]
        assert "status" not in compressed["schema"]
        
        # "tag" is "default" in 27/30 (>90%) -> in defaults, and in schema to show deviations
        assert "tag" in compressed["defaults"]
        assert "tag" in compressed["schema"]
        
        # Truncation: should have keep_first and keep_last, plus omitted placeholder
        rows = compressed["rows"]
        assert len(rows) == 11  # 5 + 1 placeholder + 5
        assert "ref" in rows[5]
        assert rows[5]["omitted"] == 20
        
        # Retrieve omitted data from cache
        omitted = registry.ccr_retrieve(rows[5]["ref"])
        assert len(omitted) == 20
        assert omitted[0]["id"] == 5
    finally:
        registry.db_path = old_db


def test_compress_json_recursive(tmp_path):
    from src.pyrtk.core.json_compress import compress_json
    from src.pyrtk.registry import registry
    
    old_db = registry.db_path
    registry.db_path = tmp_path / "test_registry_rec.db"
    registry._init_db()

    try:
        # Data wrapped inside nested dictionary and lists
        nested_data = {
            "meta": {"code": 200},
            "response": {
                "items": [
                    {"id": i, "status": "active"}
                    for i in range(30)
                ]
            }
        }
        
        res = compress_json(nested_data, max_rows=10)
        compressed = res["compressed"]
        
        # Verify it traversed and compressed the list of dicts under 'items'
        assert "meta" in compressed
        assert "response" in compressed
        items_comp = compressed["response"]["items"]
        assert "schema" in items_comp
        assert "defaults" in items_comp
        assert len(items_comp["rows"]) == 11
    finally:
        registry.db_path = old_db


def test_read_size_guard(tmp_path, monkeypatch):
    from src.pyrtk.mcp_server import rtk_run_command
    # Set limit to 20 characters
    monkeypatch.setenv("RTK_READ_MAX_CHARS", "20")
    
    test_file = tmp_path / "large_file.txt"
    test_file.write_text("abcdefghijklmnopqrstuvwxyz", encoding="utf-8")
    
    res = rtk_run_command(f"read {test_file.name}", cwd=str(tmp_path))
    assert "[... file truncated at 20 chars]" in res
    assert "abcdefghijklmnopqrst" in res
    assert "z" not in res


def test_git_optimised_command():
    from src.pyrtk.cmds.git import get_optimised_git_command
    
    assert get_optimised_git_command(["git", "status"]) == ["git", "status", "--porcelain"]
    assert get_optimised_git_command(["git", "diff"]) == ["git", "diff", "--stat"]
    assert get_optimised_git_command(["git", "diff", "HEAD~1"]) == ["git", "diff", "--stat", "HEAD~1"]
    assert get_optimised_git_command(["git", "diff", "--name-only"]) == ["git", "diff", "--name-only"]
    assert get_optimised_git_command(["git", "log"]) == ["git", "log", "--oneline"]
    assert get_optimised_git_command(["git", "log", "--oneline"]) == ["git", "log", "--oneline"]
    assert get_optimised_git_command(["git", "log", "--format=%s"]) == ["git", "log", "--format=%s"]


def test_git_diff_filter_custom_options():
    from src.pyrtk.cmds.git import _filter_diff
    
    # Custom stat option `--name-only` should pass through verbatim
    assert _filter_diff("src/foo.py\nsrc/bar.py", ["--name-only"]) == "src/foo.py\nsrc/bar.py"
    # Unified patch `-p` option should truncate to 400 chars
    long_diff = "diff --git a/foo b/bar\n" + "a" * 500
    assert len(_filter_diff(long_diff, ["-p"])) == 400


def test_aggressive_brace_nesting():
    from src.pyrtk.core.filter import _aggressive_brace
    
    # Body containing nested braces
    content = (
        "void process() {\n"
        "    if (true) {\n"
        "        doSomething();\n"
        "    }\n"
        "}\n"
    )
    # Aggressive brace should collapse the body but keep signatures
    filtered = _aggressive_brace(content)
    assert "process() {" in filtered
    assert "  ..." in filtered
    assert "doSomething" not in filtered


def test_minimal_filter_triple_quote():
    from src.pyrtk.core.filter import _minimal_filter
    
    python_code = (
        'def test():\n'
        '    """\n'
        '    This is a docstring\n'
        '    # not a comment line\n'
        '    """\n'
        '    pass\n'
    )
    filtered = _minimal_filter(python_code, "python")
    # Comment prefix '#' inside triple quotes should NOT be stripped
    assert "# not a comment line" in filtered
