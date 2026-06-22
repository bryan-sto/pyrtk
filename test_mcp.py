# test_mcp.py
from mcp_server import rtk_run_command
print("Running git status...")
out = rtk_run_command("git status")
print("Result:")
print(out)
