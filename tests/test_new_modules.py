# tests/test_new_modules.py
from __future__ import annotations

import pytest

from src.pyrtk.cmds.err_cmd import _filter_errors
from src.pyrtk.cmds.find_cmd import _filter_find
from src.pyrtk.cmds.grep_cmd import _filter_grep
from src.pyrtk.cmds.pip_cmd import _filter_list, _filter_show
from src.pyrtk.cmds.test_cmd import _filter_test_output
from src.pyrtk.core.filter import FilterLevel, code_filter, structure_only

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
    import subprocess
    import sys

    from src.pyrtk.registry import ProcessRegistry

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
    import json
    import sys
    import time

    from src.pyrtk.mcp_server import rtk_check_background, rtk_run_command

    # Run background python sleep process
    cmd = f'"{sys.executable}" -c "import time; time.sleep(0.8); print(\'done\')"'
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


def test_aggressive_python_multiline_signature():
    from src.pyrtk.core.filter import _aggressive_python

    code = (
        "def compute_metrics(\n"
        "    dataset_id: str,\n"
        "    batch_size: int = 64,\n"
        "    options: dict | None = None,\n"
        ") -> dict[str, float]:\n"
        '    """Calculate metrics for batch."""\n'
        "    res = {}\n"
        "    for item in items:\n"
        "        process(item)\n"
        "    return res\n"
    )
    out = _aggressive_python(code)
    # Entire multi-line signature and docstring preserved
    assert "def compute_metrics(" in out
    assert "dataset_id: str," in out
    assert "batch_size: int = 64," in out
    assert ") -> dict[str, float]:" in out
    assert '"""Calculate metrics for batch."""' in out
    assert "..." in out
    # Body dropped
    assert "process(item)" not in out
    assert "res = {}" not in out


def test_aggressive_brace_allman_style():
    from src.pyrtk.core.filter import _aggressive_brace

    code = (
        "public class OrderService\n"
        "{\n"
        "    public async Task ProcessOrder(Guid id)\n"
        "    {\n"
        "        var order = await _repo.GetAsync(id);\n"
        "        order.Complete();\n"
        "    }\n"
        "}\n"
    )
    out = _aggressive_brace(code)
    assert "OrderService" in out
    assert "ProcessOrder" in out or "..." in out
    assert "order.Complete()" not in out


def test_minimal_filter_js_template_literal():
    from src.pyrtk.core.filter import _minimal_filter

    js_code = (
        "const query = `\n"
        "// this comment is inside a backtick template string\n"
        "SELECT * FROM users\n"
        "`;\n"
        "// this is an actual JS comment\n"
        "console.log(query);\n"
    )
    out = _minimal_filter(js_code, "javascript")
    assert "// this comment is inside a backtick template string" in out
    assert "// this is an actual JS comment" not in out
    assert "console.log(query);" in out


def test_scrub_secrets():
    from src.pyrtk.core.utils import scrub_secrets

    # Bearer tokens
    raw1 = 'curl -H "Authorization: Bearer sk-ant-api03-abcdef123456" https://api.com'
    scrubbed1 = scrub_secrets(raw1)
    assert "sk-ant-api03" not in scrubbed1
    assert "Authorization [REDACTED]" in scrubbed1 or "Bearer [REDACTED]" in scrubbed1

    # Basic auth in URL
    raw2 = "git clone https://bryan:super_secret_token@github.com/repo.git"
    scrubbed2 = scrub_secrets(raw2)
    assert "super_secret_token" not in scrubbed2
    assert "[REDACTED]" in scrubbed2

    # curl -u
    raw3 = "curl -u admin:mypassword123 https://example.com"
    scrubbed3 = scrub_secrets(raw3)
    assert "mypassword123" not in scrubbed3
    assert "admin:[REDACTED]" in scrubbed3


def test_estimate_tokens():
    from src.pyrtk.core.utils import estimate_tokens

    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("a" * 40) == 10


def test_docker_ps_space_separated():
    from src.pyrtk.cmds.docker_cmd import _filter_ps

    raw = (
        "CONTAINER ID   IMAGE          COMMAND                  CREATED         STATUS         PORTS     NAMES\n"
        "a1b2c3d4e5f6   redis:alpine   \"docker-entrypoint.s…\"   2 minutes ago   Up 2 minutes   6379/tcp   my-redis\n"
        "1234567890ab   postgres:16    \"docker-entrypoint.s…\"   1 hour ago      "
        "Up 1 hour      5432/tcp   my-postgres\n"
    )
    out = _filter_ps(raw)
    assert "CONTAINER ID | IMAGE | STATUS | NAMES" in out
    assert "a1b2c3d4e5f6" in out
    assert "my-redis" in out
    assert "1234567890ab" in out
    assert "my-postgres" in out


def test_git_status_large_list():
    from src.pyrtk.cmds.git import _filter_status

    # Generate 25 modified files in porcelain format
    raw = "\n".join(f" M src/file_{i}.py" for i in range(25))
    out = _filter_status(raw)
    assert "modified: M src/file_0.py" in out
    assert "(+10 more files)" in out


def test_git_diff_preserves_file_stats():
    from src.pyrtk.cmds.git import _filter_diff

    raw = (
        " src/foo.py | 12 ++++++------\n"
        " src/bar.py |  4 ++--\n"
        " 2 files changed, 8 insertions(+), 8 deletions(-)\n"
    )
    out = _filter_diff(raw, [])
    assert "src/foo.py | 12 ++++++------" in out
    assert "2 files changed, 8 insertions(+), 8 deletions(-)" in out


def test_cargo_filters():
    from src.pyrtk.cmds.cargo_cmd import _filter_cargo_clippy, _filter_cargo_test

    # Cargo test
    raw_test = (
        "running 5 tests\n"
        "test tests::test_ok ... ok\n"
        "test tests::test_fail ... FAILED\n\n"
        "failures:\n"
        "---- tests::test_fail stdout ----\n"
        "thread 'tests::test_fail' panicked at src/lib.rs:10:5:\n"
        "assertion `left == right` failed\n\n"
        "failures:\n"
        "    tests::test_fail\n\n"
        "test result: FAILED. 4 passed; 1 failed; 0 ignored\n"
    )
    out_test = _filter_cargo_test(raw_test, 1)
    assert "failures:" in out_test
    assert "test result: FAILED." in out_test
    assert "test tests::test_ok ... ok" not in out_test

    # Cargo clippy
    raw_clippy = (
        "warning: unused variable: `x`\n"
        " --> src/main.rs:2:9\n"
        "  |\n"
        "2 |     let x = 42;\n"
        "  |         ^ help: if this is intentional, prefix it with an underscore: `_x`\n"
    )
    out_clippy = _filter_cargo_clippy(raw_clippy)
    assert "clippy: 1 diagnostic(s)" in out_clippy


def test_process_registry_local_stats(tmp_path):
    from src.pyrtk.registry import ProcessRegistry

    reg = ProcessRegistry(db_dir=tmp_path)
    reg.log_command("2026-09-09T00:00:00Z", "test_proj", "git status", 100, 20, 80, 80.0, 15)
    reg.log_command("2026-09-09T00:01:00Z", "test_proj", "git diff", 200, 50, 150, 75.0, 25)

    stats = reg.get_local_stats()
    assert stats["total_commands"] == 2
    assert stats["total_input_t"] == 300
    assert stats["total_output_t"] == 70
    assert stats["total_saved_t"] == 230
    assert stats["avg_pct"] == 77.5


def test_rtk_kill_background(tmp_path):
    import json
    import sys
    import time

    from src.pyrtk.mcp_server import rtk_check_background, rtk_kill_background, rtk_run_command

    # Run long background process
    cmd = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    res_str = rtk_run_command(cmd, cwd=str(tmp_path), background=True)
    res = json.loads(res_str)
    handle_id = res["handle_id"]

    # Verify alive
    status1 = json.loads(rtk_check_background(handle_id))
    assert status1["alive"] is True

    # Kill process
    kill_res = json.loads(rtk_kill_background(handle_id))
    assert kill_res["killed"] is True

    time.sleep(0.5)

    # Verify dead
    status2 = json.loads(rtk_check_background(handle_id))
    assert status2["alive"] is False


def test_unified_dispatcher():
    from src.pyrtk.core.dispatcher import dispatch_command

    res = dispatch_command(["read", "pyproject.toml", "minimal"])
    assert res.exit_code == 0
    assert "[project]" in res.filtered
    assert len(res.filtered) > 0


def test_docker_ps_preserves_extra_args(monkeypatch):
    from src.pyrtk.core.dispatcher import dispatch_command

    executed_cmd = []

    def mock_execute(cmd, cwd="."):
        executed_cmd.extend(cmd)
        return ("", "", 0)

    monkeypatch.setattr("src.pyrtk.core.dispatcher.execute_command", mock_execute)
    dispatch_command(["docker", "ps", "-a", "--filter", "name=test_box"])

    assert "-a" in executed_cmd
    assert "--filter" in executed_cmd
    assert "name=test_box" in executed_cmd


def test_ruff_check_json_and_hyphen_format():
    import json

    from src.pyrtk.cmds.ruff_cmd import _filter_check_json

    sample = [
        {
            "code": "F401",
            "filename": "src/test.py",
            "location": {"row": 1},
            "message": "`os` imported but unused",
        }
    ]
    out = _filter_check_json(json.dumps(sample))
    assert out is not None
    assert "ruff: 1 violation(s) - 1 rule(s)" in out
    assert "—" not in out
    assert "src/test.py:1" in out


def test_python_find_outside_cwd(tmp_path):
    from src.pyrtk.cmds.find_cmd import _python_find

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    target_file = outside_dir / "target.py"
    target_file.write_text("print('hello')", encoding="utf-8")

    sub_cwd = tmp_path / "inside"
    sub_cwd.mkdir()

    results = _python_find([str(outside_dir)], cwd=str(sub_cwd))
    assert len(results) == 1
    assert "target.py" in results[0]


def test_grep_filter_windows_path_and_no_em_dash():
    from src.pyrtk.cmds.grep_cmd import _filter_grep

    raw = (
        r"C:\workspace\app\main.py:15:    print('hello world')" + "\n"
        r"C:\workspace\app\utils.py:    return True" + "\n"
    )
    out = _filter_grep(raw)
    assert "2 match(es) in 2 file(s)" in out
    assert "—" not in out
    assert "-" in out


def test_utc_now_iso():
    import datetime

    from src.pyrtk.core.utils import utc_now_iso

    ts = utc_now_iso()
    assert ts.endswith("Z")
    assert "+00:00Z" not in ts
    parsed = datetime.datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


def test_split_command_windows_nested_quotes():
    from src.pyrtk.core.utils import split_command

    assert split_command('powershell -Command "Write-Host \'hi\'"', is_windows=True) == [
        "powershell",
        "-Command",
        "Write-Host 'hi'",
    ]
    assert split_command("echo '\"inner\"'", is_windows=True) == ["echo", '"inner"']


def test_split_command_windows_escaped_inner_double_quotes():
    from src.pyrtk.core.utils import split_command

    assert split_command('python -c "print(\\"hello\\")"', is_windows=True) == [
        "python",
        "-c",
        'print("hello")',
    ]


def test_split_command_windows_backslashes():
    from src.pyrtk.core.utils import split_command

    assert split_command(r"cat C:\Users\foo\bar.txt", is_windows=True) == [
        "cat",
        r"C:\Users\foo\bar.txt",
    ]
    assert split_command(r'cat "C:\Users\foo bar\baz.txt"', is_windows=True) == [
        "cat",
        r"C:\Users\foo bar\baz.txt",
    ]


def test_split_command_windows_empty_quoted_strings():
    from src.pyrtk.core.utils import split_command

    assert split_command('cmd "" \'\'', is_windows=True) == ["cmd", "", ""]
    assert split_command('""', is_windows=True) == [""]
    assert split_command("", is_windows=True) == []


def test_split_command_posix():
    from src.pyrtk.core.utils import split_command

    assert split_command('echo "hello world" \'foo bar\'', is_windows=False) == [
        "echo",
        "hello world",
        "foo bar",
    ]


def test_rtk_run_background_resolves_cmd_executable(tmp_path, monkeypatch):
    import json
    import subprocess
    from types import SimpleNamespace

    from src.pyrtk.mcp_server import rtk_run_command

    resolved_target = str(tmp_path / "npm.cmd")
    captured: dict = {}

    def fake_resolve(cmd_name, path=None):
        captured["resolved_input"] = cmd_name
        return resolved_target

    def fake_popen(cmd, **kwargs):
        captured["popen_cmd"] = cmd
        return SimpleNamespace(pid=4242, poll=lambda: None)

    monkeypatch.setattr("src.pyrtk.mcp_server.resolve_executable", fake_resolve)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    res = json.loads(rtk_run_command("npm run dev", cwd=str(tmp_path), background=True))
    assert res["pid"] == 4242
    assert "handle_id" in res
    assert captured["resolved_input"] == "npm"
    assert captured["popen_cmd"] == [resolved_target, "run", "dev"]


def test_rtk_run_background_sanitizes_log_filename(tmp_path, monkeypatch):
    import json
    import subprocess
    from types import SimpleNamespace

    from src.pyrtk.mcp_server import rtk_run_command

    def fake_popen(cmd, **kwargs):
        return SimpleNamespace(pid=5150, poll=lambda: None)

    monkeypatch.setattr("src.pyrtk.mcp_server.resolve_executable", lambda c, path=None: c)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    res = json.loads(rtk_run_command("./sub/my@app.sh --watch", cwd=str(tmp_path), background=True))
    assert res["pid"] == 5150

    log_files = list((tmp_path / ".pyrtk_logs").iterdir())
    names = [p.name for p in log_files]
    assert any(n.startswith("my_app_") and n.endswith("_stdout.log") for n in names)
    assert any(n.startswith("my_app_") and n.endswith("_stderr.log") for n in names)


def test_rtk_run_bg_patterns_scoped_to_head(tmp_path, monkeypatch):
    import json
    import subprocess
    from types import SimpleNamespace

    from src.pyrtk.mcp_server import rtk_run_command

    calls = {"dispatch": 0, "popen": 0}

    def fake_dispatch(args, cwd="."):
        calls["dispatch"] += 1
        return SimpleNamespace(raw="ok", filtered="ok", exit_code=0, exec_ms=1)

    def fake_popen(cmd, **kwargs):
        calls["popen"] += 1
        return SimpleNamespace(pid=6161, poll=lambda: None)

    monkeypatch.setattr("src.pyrtk.mcp_server.dispatch_command", fake_dispatch)
    monkeypatch.setattr("src.pyrtk.mcp_server._log", lambda *a, **kw: None)
    monkeypatch.setattr("src.pyrtk.mcp_server.resolve_executable", lambda c, path=None: c)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    sync_out = rtk_run_command('git commit -m "fix npm run dev"', cwd=str(tmp_path))
    assert sync_out == "ok"
    assert calls["dispatch"] == 1
    assert calls["popen"] == 0

    bg_out = json.loads(rtk_run_command("npm run dev", cwd=str(tmp_path)))
    assert bg_out["pid"] == 6161
    assert calls["dispatch"] == 1
    assert calls["popen"] == 1


def test_scrub_secrets_tightened_no_false_positives():
    from src.pyrtk.core.utils import scrub_secrets

    # Normal English phrases should NOT be redacted
    msg = 'git commit -m "fix auth middleware"'
    assert scrub_secrets(msg) == msg
    assert scrub_secrets("token savings report") == "token savings report"

    # Explicit assignments ARE redacted
    assert "abc123" not in scrub_secrets("token=abc123")
    assert "[REDACTED]" in scrub_secrets("token=abc123")
    assert "xyz" not in scrub_secrets("api_key: xyz")
    assert "p@ss" not in scrub_secrets('password="p@ss"')

    # CLI flags ARE redacted
    assert "xyz" not in scrub_secrets("cli --api-key xyz")
    assert "[REDACTED]" in scrub_secrets("cli --api-key xyz")
    assert "abc" not in scrub_secrets("cli --token abc")
    assert "pw" not in scrub_secrets("cli --password pw")
    assert "mysecret" not in scrub_secrets("cli --secret mysecret")


def test_write_tee_log_scrubs_and_unique(tmp_path, monkeypatch):
    import re
    from pathlib import Path

    from src.pyrtk.core.dispatcher import _write_tee_log

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    p1 = _write_tee_log("pytest", "Error with token=supersecret123 and --api-key mykey999")
    p2 = _write_tee_log("pytest", "Second failure")

    assert p1 is not None and p2 is not None
    assert p1 != p2

    path1 = Path(p1)
    assert re.match(r"^\d+_[0-9a-f]{6}_pytest\.log$", path1.name)
    content = path1.read_text(encoding="utf-8")
    assert "supersecret123" not in content
    assert "mykey999" not in content
    assert "[REDACTED]" in content


def test_process_sweep_prunes_old_tee_logs(tmp_path, monkeypatch):
    import os
    import time
    from pathlib import Path

    from src.pyrtk.registry import ProcessRegistry

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    tee_dir = tmp_path / ".pyrtk" / "tee"
    tee_dir.mkdir(parents=True)

    old_log = tee_dir / "old_test.log"
    new_log = tee_dir / "new_test.log"
    old_log.write_text("old", encoding="utf-8")
    new_log.write_text("new", encoding="utf-8")

    old_mtime = time.time() - 100
    os.utime(old_log, (old_mtime, old_mtime))

    reg = ProcessRegistry(db_dir=tmp_path / "db")
    reg.process_sweep(max_age_seconds=50, force=True)

    assert not old_log.exists()
    assert new_log.exists()
    reg.close()


def test_registry_secondary_indexes_and_persistent_connection(tmp_path):
    from src.pyrtk.registry import ProcessRegistry

    reg = ProcessRegistry(db_dir=tmp_path)
    try:
        conn1 = reg._connect()
        conn2 = reg._connect()
        assert conn1 is conn2

        indexes = {
            row[0]
            for row in conn1.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        assert "idx_cmd_history_ts" in indexes
        assert "idx_ccr_created" in indexes
        assert "idx_bg_ended_started" in indexes

        journal_mode = conn1.execute("PRAGMA journal_mode;").fetchone()[0]
        auto_vacuum = conn1.execute("PRAGMA auto_vacuum;").fetchone()[0]
        busy_timeout = conn1.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert str(journal_mode).lower() == "wal"
        assert auto_vacuum == 2
        assert busy_timeout == 10000
    finally:
        reg.close()

    assert reg._conn is None
    # Reopens cleanly on demand after close()
    assert reg.get_local_stats()["total_commands"] == 0
    reg.close()


def test_registry_command_history_pruning(tmp_path):
    import datetime

    from src.pyrtk.registry import ProcessRegistry

    reg = ProcessRegistry(db_dir=tmp_path)
    try:
        now_dt = datetime.datetime.now(datetime.UTC)
        old_ts = (now_dt - datetime.timedelta(days=45)).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        with reg._transaction() as conn:
            # Insert expired rows (>30 days)
            for i in range(5):
                conn.execute(
                    """
                    INSERT INTO command_history (timestamp, project, command, input_t, output_t, saved_t, pct, exec_ms)
                    VALUES (?, 'proj', ?, 10, 5, 5, 50.0, 1)
                    """,
                    (old_ts, f"old_{i}"),
                )
            # Insert 5,020 recent rows with strictly increasing timestamps
            base_dt = now_dt - datetime.timedelta(hours=2)
            rows = [
                (
                    (base_dt + datetime.timedelta(seconds=i)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "proj",
                    f"cmd_{i}",
                    10,
                    5,
                    5,
                    50.0,
                    1,
                )
                for i in range(5020)
            ]
            conn.executemany(
                """
                INSERT INTO command_history (timestamp, project, command, input_t, output_t, saved_t, pct, exec_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        reg.process_sweep(force=True)

        with reg._transaction() as conn:
            total = conn.execute("SELECT COUNT(*) FROM command_history").fetchone()[0]
            old_left = conn.execute(
                "SELECT COUNT(*) FROM command_history WHERE command LIKE 'old_%'"
            ).fetchone()[0]
            dropped_oldest = conn.execute(
                "SELECT COUNT(*) FROM command_history WHERE command = 'cmd_0'"
            ).fetchone()[0]
            kept_newest = conn.execute(
                "SELECT COUNT(*) FROM command_history WHERE command = 'cmd_5019'"
            ).fetchone()[0]

        assert total == 5000
        assert old_left == 0
        assert dropped_oldest == 0
        assert kept_newest == 1
    finally:
        reg.close()


def test_registry_startup_sweeps_dead_pids(tmp_path):
    import os
    import time

    import psutil

    from src.pyrtk.registry import ProcessRegistry

    reg1 = ProcessRegistry(db_dir=tmp_path)
    alive_pid = os.getpid()
    alive_ctime = psutil.Process(alive_pid).create_time()

    with reg1._transaction() as conn:
        # Dead / nonexistent PID
        conn.execute(
            """
            INSERT INTO background_processes (handle_id, pid, cmd, stdout_log, stderr_log, started_at)
            VALUES ('dead-1', 99999999, '["sleep"]', 'out.log', 'err.log', ?)
            """,
            (time.time(),),
        )
        # Recycled PID (started_at far from current process create_time)
        conn.execute(
            """
            INSERT INTO background_processes (handle_id, pid, cmd, stdout_log, stderr_log, started_at)
            VALUES ('recycled-1', ?, '["sleep"]', 'out.log', 'err.log', ?)
            """,
            (alive_pid, alive_ctime - 1000.0),
        )
        # Genuinely alive PID
        conn.execute(
            """
            INSERT INTO background_processes (handle_id, pid, cmd, stdout_log, stderr_log, started_at)
            VALUES ('alive-1', ?, '["sleep"]', 'out.log', 'err.log', ?)
            """,
            (alive_pid, alive_ctime),
        )
    reg1.close()

    reg2 = ProcessRegistry(db_dir=tmp_path)
    try:
        dead_entry = reg2.get("dead-1")
        assert dead_entry.ended_at is not None
        assert dead_entry.exit_code == -1

        recycled_entry = reg2.get("recycled-1")
        assert recycled_entry.ended_at is not None
        assert recycled_entry.exit_code == -1

        alive_entry = reg2.get("alive-1")
        assert alive_entry.ended_at is None
        assert alive_entry.exit_code is None
    finally:
        reg2.close()


def test_registry_sweep_rate_limit_and_incremental_vacuum(tmp_path, monkeypatch):
    import os
    from pathlib import Path

    from src.pyrtk.registry import CCR_MAX_DB_BYTES, ProcessRegistry

    reg = ProcessRegistry(db_dir=tmp_path)
    try:
        # Insert an already-expired CCR entry directly without triggering sweep
        with reg._transaction() as conn:
            conn.execute(
                """
                INSERT INTO ccr_cache (ref, original, created_at, ttl_seconds, source_tool)
                VALUES ('ccr_expired', X'789c', 1.0, 1, 'test')
                """
            )

        # Within 300s rate limit, force=False skips sweep
        reg.ccr_sweep()
        with reg._transaction() as conn:
            assert conn.execute("SELECT COUNT(*) FROM ccr_cache").fetchone()[0] == 1

        # Populate 5 valid entries and simulate >500 MB db_path
        for i in range(5):
            reg.ccr_store({"i": i})

        real_stat = Path.stat

        def fake_stat(self, *args, **kwargs):
            st = real_stat(self, *args, **kwargs)
            if self == reg.db_path:
                return os.stat_result(
                    (
                        st.st_mode,
                        st.st_ino,
                        st.st_dev,
                        st.st_nlink,
                        st.st_uid,
                        st.st_gid,
                        CCR_MAX_DB_BYTES + 1024,
                        st.st_atime,
                        st.st_mtime,
                        st.st_ctime,
                    )
                )
            return st

        monkeypatch.setattr(Path, "stat", fake_stat)
        reg.ccr_sweep(force=True)

        with reg._transaction() as conn:
            # Expired row removed, and 1/5 of the 5 remaining rows (1 row) evicted
            remaining = conn.execute("SELECT COUNT(*) FROM ccr_cache").fetchone()[0]
        assert remaining == 4
    finally:
        reg.close()


def test_registry_lazy_proxy(tmp_path, monkeypatch):
    from pathlib import Path

    import src.pyrtk.registry as reg_mod

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    old_instance = reg_mod._registry_instance
    reg_mod._registry_instance = None

    try:
        assert reg_mod._registry_instance is None
        assert "uninitialized" in repr(reg_mod.registry)
        assert reg_mod._registry_instance is None

        # Accessing an attribute initializes the singleton lazily
        db_path = reg_mod.registry.db_path
        assert reg_mod._registry_instance is not None
        assert db_path.exists()
        assert reg_mod.get_registry() is reg_mod._registry_instance
    finally:
        if reg_mod._registry_instance is not None:
            reg_mod._registry_instance.close()
        reg_mod._registry_instance = old_instance


