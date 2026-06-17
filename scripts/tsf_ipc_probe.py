from __future__ import annotations

import json
import argparse
import subprocess
import sys
import threading
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hebrew_live_dictation.tsf_ipc import NamedPipeHandshakeServer, send_test_hello


def run_native_peer(native_peer: str, pipe_name: str, session_id: str, nonce: str, timeout_ms: int) -> dict:
    try:
        completed = subprocess.run(
            [
                native_peer,
                "--pipe",
                pipe_name,
                "--session",
                session_id,
                "--nonce",
                nonce,
                "--timeout-ms",
                str(timeout_ms),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout_ms / 1000.0 + 1.0),
        )
        output = (completed.stdout or completed.stderr or "").strip()
        parsed = json.loads(output) if output.startswith("{") else {"raw_output": output}
        parsed["exit_code"] = completed.returncode
        return parsed
    except Exception as e:
        return {"ok": False, "status": "native_peer_error", "reason": f"{type(e).__name__}:{e}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the VoiceType TSF Named Pipe hello handshake.")
    parser.add_argument("--native-peer", help="Optional path to VoiceTypeTsfHelloPeer.exe.")
    parser.add_argument("--timeout-ms", type=int, default=150)
    args = parser.parse_args()

    session_id = uuid.uuid4().hex
    nonce = uuid.uuid4().hex
    pipe_name = rf"\\.\pipe\VoiceType-Probe-{session_id}"
    client_response: list[dict] = []

    if args.native_peer:
        client = threading.Thread(
            target=lambda: client_response.append(
                run_native_peer(args.native_peer, pipe_name, session_id, nonce, args.timeout_ms)
            ),
            daemon=True,
        )
    else:
        client = threading.Thread(
            target=lambda: client_response.append(send_test_hello(pipe_name, session_id, nonce)),
            daemon=True,
        )

    client.start()
    server_result = NamedPipeHandshakeServer(pipe_name, session_id, nonce, timeout_ms=args.timeout_ms).run()
    client.join(timeout=1)

    print(
        json.dumps(
            {
                "server": {
                    "ok": server_result.ok,
                    "status": server_result.status,
                    "reason": server_result.reason,
                },
                "client": client_response[0] if client_response else {"ok": False, "status": "missing_response"},
                "pipe_name": pipe_name,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if server_result.ok and client_response and client_response[0].get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
