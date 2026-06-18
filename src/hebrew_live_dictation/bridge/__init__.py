"""WinUI shell <-> engine IPC bridge (thin adapter; no engine modules are modified)."""

from .server import DEFAULT_PIPE_NAME, NamedPipeJsonRpcServer
from .sidecar import run

__all__ = ["run", "NamedPipeJsonRpcServer", "DEFAULT_PIPE_NAME"]
