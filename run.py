#!/usr/bin/env python3
"""Run from the project checkout without installing a package."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    from eels_sim.server import main
    main()
