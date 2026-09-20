# mcp_server.py
from __future__ import annotations

import sys
from pathlib import Path

# Path guard to ensure package imports resolve correctly in all cwd contexts
sys.path.insert(0, str(Path(__file__).parent / "src"))

from pyrtk.mcp_server import main, mcp  # noqa: F401

if __name__ == "__main__":
    main()
