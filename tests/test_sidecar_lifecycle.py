import ctypes
import json
import os
import subprocess
import sys
import time
import unittest
from ctypes import wintypes


def _pid_alive(pid: int) -> bool:
    """True if the process is still running (Windows)."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k = ctypes.windll.kernel32
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def _kill_pid(pid: int) -> None:
    try:
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if h:
            k.TerminateProcess(h, 1)
            k.CloseHandle(h)
    except Exception:
        pass


class _Client:
    """Single-threaded pipe client (serialized write->read; no concurrent I/O)."""

    def __init__(self, name, timeout=20.0):
        deadline = time.time() + timeout
        self.f = None
        while time.time() < deadline:
            try:
                self.f = open(name, "r+b", buffering=0)
                break
            except OSError:
                time.sleep(0.1)
        if self.f is None:
            raise TimeoutError("pipe never became available")
        self._buf = b""

    def _read(self):
        while b"\n" not in self._buf:
            chunk = self.f.read(4096)
            if not chunk:
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def rpc(self, method, rid):
        self.f.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method}) + "\n").encode())
        self.f.flush()
        while True:
            msg = self._read()
            if msg is None:
                raise EOFError("pipe closed")
            if msg.get("method") == "event":
                continue
            if msg.get("id") == rid:
                return msg

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


@unittest.skipUnless(sys.platform == "win32", "named-pipe sidecar is Windows-only")
class SidecarLifecycleTests(unittest.TestCase):
    def test_nonce_pipe_ownership_and_clean_shutdown(self):
        nonce = os.urandom(6).hex()
        pipe = r"\\.\pipe\voicetype-test-" + nonce

        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.join(repo, "src") + os.pathsep + env.get("PYTHONPATH", "")
        # The venv python.exe may be a launcher stub that re-spawns the real
        # interpreter as a child, so we track the sidecar by its reported pid rather
        # than the Popen pid.
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "hebrew_live_dictation.bridge", "--pipe", pipe],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.addCleanup(lambda: (proc.poll() is None) and proc.kill())

        client = None
        sidecar_pid = None
        try:
            client = _Client(pipe)

            ping = client.rpc("ping", 1).get("result", {})
            self.assertTrue(ping.get("ok"))
            sidecar_pid = ping.get("pid")
            self.assertIsInstance(sidecar_pid, int)

            status = client.rpc("getStatus", 2).get("result", {})
            self.assertEqual(status.get("state"), "idle")
            # Ownership: the sidecar runs on the unique nonce pipe we created — a
            # stale/orphan sidecar (default pipe) can never serve this name.
            self.assertEqual(status.get("pipe"), pipe)

            ack = client.rpc("shutdown", 3).get("result", {})
            self.assertTrue(ack.get("accepted"))
        finally:
            if client:
                client.close()

        # Clean shutdown: the sidecar exits on its own (no hard kill required).
        deadline = time.time() + 12
        while time.time() < deadline and _pid_alive(sidecar_pid):
            time.sleep(0.1)
        alive = _pid_alive(sidecar_pid)
        if alive:
            _kill_pid(sidecar_pid)
        self.assertFalse(alive, "sidecar did not exit cleanly after shutdown RPC")


if __name__ == "__main__":
    unittest.main()
