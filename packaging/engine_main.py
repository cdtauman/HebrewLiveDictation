"""PyInstaller entry point for the headless engine sidecar, frozen as ``engine.exe``.

Mirrors ``python -m hebrew_live_dictation.bridge``: ``sidecar.run()`` parses ``--pipe``
from argv and serves the named-pipe JSON-RPC the WinUI shell connects to. Kept intentionally
tiny so the freeze surface is exactly the engine — no UI, no shell code.
"""

import sys

from hebrew_live_dictation.bridge.sidecar import run

if __name__ == "__main__":
    sys.exit(run())
