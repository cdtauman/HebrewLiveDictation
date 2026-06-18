import json
import os
import time
import unittest

from hebrew_live_dictation.bridge.server import NamedPipeJsonRpcServer


class _Client:
    """Single-threaded pipe client (serialized write->read; no concurrent I/O)."""

    def __init__(self, name, timeout=5.0):
        deadline = time.time() + timeout
        self.f = None
        while time.time() < deadline:
            try:
                self.f = open(name, "r+b", buffering=0)
                break
            except OSError:
                time.sleep(0.05)
        if self.f is None:
            raise TimeoutError("pipe never became available")
        self._buf = b""

    def read_msg(self):
        while b"\n" not in self._buf:
            chunk = self.f.read(4096)
            if not chunk:
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def rpc(self, method, params=None, rid=1):
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        self.f.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.f.flush()
        return self.read_msg()

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


class BridgeServerTests(unittest.TestCase):
    def _unique_name(self):
        return r"\\.\pipe\voicetype-test-" + os.urandom(6).hex()

    def test_request_response_error_and_async_event(self):
        name = self._unique_name()

        def handler(method, params):
            if method == "ping":
                return {"ok": True}
            if method == "add":
                return {"sum": params["a"] + params["b"]}
            raise ValueError("unknown method")

        server = NamedPipeJsonRpcServer(handler, name=name)
        server.start()
        client = _Client(name)
        try:
            r = client.rpc("ping", rid=1)
            self.assertEqual(r.get("id"), 1)
            self.assertTrue(r["result"]["ok"])

            r = client.rpc("add", {"a": 2, "b": 3}, rid=2)
            self.assertEqual(r["result"]["sum"], 5)

            r = client.rpc("bad", rid=3)
            self.assertIn("error", r)
            self.assertEqual(r.get("id"), 3)

            # Async server->client push must work while the read loop is blocked
            # (overlapped I/O): event has no id and method == "event".
            self.assertTrue(server.send_event({"kind": "hello", "n": 7}))
            evt = client.read_msg()
            self.assertEqual(evt.get("method"), "event")
            self.assertEqual(evt["params"]["kind"], "hello")
            self.assertEqual(evt["params"]["n"], 7)
        finally:
            client.close()
            server.stop()


if __name__ == "__main__":
    unittest.main()
