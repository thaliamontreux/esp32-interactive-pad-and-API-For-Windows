#!/usr/bin/env python3
"""Simple script to run the DisplayPad Server."""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src_path))

from displaypad_server.launcher import main

if __name__ == "__main__":
    main()
