"""Uvicorn entry point bound to loopback only (development prototype, not production)."""
from __future__ import annotations

import argparse
import socket
import threading
from pathlib import Path

import uvicorn

from ..app_service import AppService
from ..openrouter import create_openrouter_adapter_from_env, inspect_openrouter_env_status
from .app import create_app

DEFAULT_PORT = 8765


class LocalServer:
    """Uvicorn server on a pre-bound 127.0.0.1 socket.

    Mirrors the small part of `socketserver` the team scripts and HTTP tests use
    (`server_port`, `serve_forever`, `shutdown`, `server_close`, context manager), so the
    contract tests exercise the real FastAPI/Uvicorn stack instead of a test client.
    """

    def __init__(self, service: AppService, port: int = DEFAULT_PORT) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", port))
        self._sock.listen(128)
        self.server_port: int = self._sock.getsockname()[1]
        config = uvicorn.Config(
            create_app(service),
            log_level="warning",
            access_log=False,          # questions/user input are never written to access logs
            server_header=False,
            date_header=False,
            lifespan="off",
            timeout_graceful_shutdown=3,
        )
        self._server = uvicorn.Server(config)
        self._started = threading.Event()
        self._stopped = threading.Event()

    def serve_forever(self) -> None:
        self._started.set()
        try:
            self._server.run(sockets=[self._sock])
        finally:
            self._stopped.set()

    def shutdown(self) -> None:
        self._server.should_exit = True
        if self._started.is_set():
            self._stopped.wait(timeout=10)

    def server_close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "LocalServer":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.shutdown()
        self.server_close()


def make_server(service: AppService, port: int = DEFAULT_PORT) -> LocalServer:
    return LocalServer(service, port)


def create_configured_service(repo_root: Path) -> tuple[AppService, dict[str, object]]:
    """Build AppService with an optional verified `:free` OpenRouter adapter."""
    env_status = inspect_openrouter_env_status(repo_root)
    adapter = create_openrouter_adapter_from_env(repo_root, strict=False)
    status_info = dict(env_status)
    status_info["adapter_active"] = adapter is not None
    return AppService(repo_root, answer_adapter=adapter), status_info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    service, openrouter_status = create_configured_service(args.repo_root)
    with make_server(service, args.port) as server:
        print(f"GenAIus local prototype: http://127.0.0.1:{server.server_port}", flush=True)
        if openrouter_status.get("adapter_active"):
            print(f"OpenRouter (:free) enabled: {openrouter_status.get('model')} (strict grounded JSON).", flush=True)
        else:
            print(f"Deterministic mode (no LLM; reason={openrouter_status.get('reason')}). Stop with Ctrl+C.",
                  flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
