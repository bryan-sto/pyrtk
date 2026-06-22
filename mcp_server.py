# mcp_server.py — thin entrypoint only
from src.pyrtk.mcp_server import mcp

if __name__ == "__main__":
    mcp.run()
