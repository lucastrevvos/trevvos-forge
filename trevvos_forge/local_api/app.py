"""Forge Local API — HTTP server factory and runner."""
from __future__ import annotations

from http.server import HTTPServer
from pathlib import Path
from typing import Type

from trevvos_forge.local_api.handler import ForgeApiHandler
from trevvos_forge.local_api.service import LocalApiService


def create_handler(service: LocalApiService) -> Type[ForgeApiHandler]:
    """Return a ForgeApiHandler subclass bound to the given service."""
    class BoundHandler(ForgeApiHandler):
        pass
    BoundHandler.service = service
    return BoundHandler


def create_server(
    *,
    workspace_root: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> HTTPServer:
    service = LocalApiService(workspace_root)
    handler_cls = create_handler(service)
    return HTTPServer((host, port), handler_cls)


def run_server(
    *,
    workspace_root: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    server = create_server(workspace_root=workspace_root, host=host, port=port)
    server.serve_forever()
