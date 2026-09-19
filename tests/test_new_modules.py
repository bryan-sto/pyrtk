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

