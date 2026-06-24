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
