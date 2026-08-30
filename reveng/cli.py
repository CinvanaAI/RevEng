"""Command-line entry point for the local RevEng web application."""
from __future__ import annotations

import argparse
from collections.abc import Sequence


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RevEng Control Center — repository analysis and capability orchestration"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Bind port (default: 8080)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable development hot-reload",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn is not installed.")
        print("       Run: python -m pip install -r requirements.txt")
        return 1

    print(f"Starting RevEng Control Center at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.\n")

    uvicorn.run(
        "reveng.platform.web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
