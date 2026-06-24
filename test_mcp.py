# test_mcp.py
from src.pyrtk.mcp_server import rtk_run_command

print("Running git status...")
out = rtk_run_command("git status")
assert isinstance(out, str), f"Expected str, got {type(out)}"
assert len(out) > 0, "Expected non-empty output"
assert "error" not in out.lower(), f"Unexpected error: {out}"
print("OK:", out)
