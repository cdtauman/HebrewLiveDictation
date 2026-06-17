import ctypes
import threading
import time
import unittest
import uuid

from hebrew_live_dictation.tsf_bridge import TSFBridge
from hebrew_live_dictation.tsf_ipc import NamedPipeHandshakeServer, send_test_hello


class DummyConfig:
    def __init__(self, values=None):
        self.values = {
            "dictation.input_backend": "tsf",
            "tsf.handshake_timeout_ms": 150,
            "tsf.experimental_transport_enabled": True,
            "tsf.allow_low_integrity_label": False,
        }
        if values:
            self.values.update(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeTarget:
    hwnd = 12345
    process_id = 222
    process_name = "notepad.exe"

    def is_usable_external(self):
        return True

    def describe(self):
        return "FakeTarget"


@unittest.skipIf(not hasattr(ctypes, "windll"), "Windows named pipes are required")
class TSFIPCTests(unittest.TestCase):
    def _pipe_name(self):
        return rf"\\.\pipe\VoiceType-Test-{uuid.uuid4().hex}"

    def test_named_pipe_handshake_accepts_valid_peer(self):
        pipe_name = self._pipe_name()
        session_id = uuid.uuid4().hex
        nonce = "nonce-ok"
        responses = []

        client = threading.Thread(
            target=lambda: responses.append(send_test_hello(pipe_name, session_id, nonce)),
            daemon=True,
        )
        client.start()

        result = NamedPipeHandshakeServer(pipe_name, session_id, nonce, timeout_ms=150).run()
        client.join(timeout=1)

        self.assertTrue(result.ok, result)
        self.assertEqual(result.status, "connected")
        self.assertTrue(responses)
        self.assertTrue(responses[0]["ok"])

    def test_named_pipe_handshake_rejects_wrong_nonce(self):
        pipe_name = self._pipe_name()
        session_id = uuid.uuid4().hex
        responses = []

        client = threading.Thread(
            target=lambda: responses.append(send_test_hello(pipe_name, session_id, "wrong")),
            daemon=True,
        )
        client.start()

        result = NamedPipeHandshakeServer(pipe_name, session_id, "expected", timeout_ms=150).run()
        client.join(timeout=1)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "nonce_mismatch")
        self.assertTrue(responses)
        self.assertFalse(responses[0]["ok"])

    def test_named_pipe_handshake_times_out_without_peer(self):
        started_at = time.monotonic()
        result = NamedPipeHandshakeServer(self._pipe_name(), uuid.uuid4().hex, "nonce", timeout_ms=50).run()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "timeout")
        self.assertLess(time.monotonic() - started_at, 0.6)

    def test_bridge_reports_connected_when_peer_handshakes(self):
        config = DummyConfig()
        bridge = TSFBridge(config)
        session_id = uuid.uuid4().hex
        nonce = "fixed-nonce"
        pipe_name = bridge._pipe_name(session_id)

        import hebrew_live_dictation.tsf_bridge as tsf_bridge_module

        original_token_hex = tsf_bridge_module.secrets.token_hex
        tsf_bridge_module.secrets.token_hex = lambda size: nonce
        try:
            client = threading.Thread(
                target=lambda: send_test_hello(pipe_name, session_id, nonce),
                daemon=True,
            )
            client.start()
            result = bridge.handshake(FakeTarget(), session_id)
            client.join(timeout=1)
        finally:
            tsf_bridge_module.secrets.token_hex = original_token_hex

        self.assertTrue(result.available, result)
        self.assertEqual(result.status, "connected")
