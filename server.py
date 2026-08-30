"""Compatibility wrapper for running RevEng from a source checkout."""

from reveng.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
