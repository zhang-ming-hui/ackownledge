"""Unified web entry point wrapper.

This module keeps the legacy multimedia launcher path working, but serves the
shared unified UI that combines IR, IE, and multimedia.
"""

from __future__ import annotations

import argparse

from unified_web.app import app as _unified_app
from unified_web.app import serve_web as _unified_serve_web


app = _unified_app


def create_app():
    return app


def serve_web(host: str = "127.0.0.1", port: int = 5002, debug: bool = False) -> None:
    _unified_serve_web(host=host, port=port, debug=debug)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified IR / IE / Multimedia web service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    serve_web(host=args.host, port=args.port, debug=args.debug)
