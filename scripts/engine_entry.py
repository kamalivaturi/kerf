"""PyInstaller entry point for the frozen engine (kerf-engine serve | run | batch | features)."""
import multiprocessing
import sys

from kerf.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
