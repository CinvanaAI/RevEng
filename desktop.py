"""RevEng desktop entry point.

Usage:
    python desktop.py

Opens the RevEng application in a native desktop window.
For development with hot-reload, use server.py instead.
"""
import sys

from reveng.desktop.launcher import launch

if __name__ == "__main__":
    sys.exit(launch())
