"""Compatibility entry point: `python -m genaius.prototype.server` → FastAPI/Uvicorn app.

The only HTTP implementation lives in `genaius.api`; this module just keeps the
historical import path and command used by team scripts and tests.
"""
from __future__ import annotations

from genaius.api.server import LocalServer, create_configured_service, main, make_server

__all__ = ["LocalServer", "create_configured_service", "main", "make_server"]

if __name__ == "__main__":
    main()
