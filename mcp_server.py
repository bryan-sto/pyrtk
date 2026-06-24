# mcp_server.py
import sys
from pathlib import Path

# Path guard to ensure relative package imports resolve correctly in all cwd contexts
sys.path.insert(0, str(Path(__file__).parent))

from src.pyrtk.mcp_server import mcp

if __name__ == "__main__":
    mcp.run()
