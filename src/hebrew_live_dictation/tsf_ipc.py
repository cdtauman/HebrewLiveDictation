from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from .tsf_protocol import FRAME_HEADER_BYTES, MAX_FRAME_BYTES, decode_frame, encode_frame


logger = logging.getLogger("TSFIPC")


PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
SDDL_REVISION_1 = 1
TOKEN_QUERY = 0x0008
TOKEN_USER = 1


@dataclass(frozen=True)
class PipeHandshake:
    ok: bool
    status: str
    reason: str = ""
    peer: dict | None = None


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class TOKEN_USER_STRUCT(ctypes.Structure):
    _fields_ = [("User", SID_AND_ATTRIBUTES)]


def _kernel32():
    return ctypes.windll.kernel32


def _advapi32():
    return ctypes.windll.advapi32


def _last_error() -> int:
    try:
        return int(_kernel32().GetLastError())
    except Exception:
        return 0


def _configure_winapi():
    if not hasattr(ctypes, "windll"):
        return
    kernel32 = _kernel32()
    advapi32 = _advapi32()

    kernel32.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel32.ConnectNamedPipe.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    kernel32.DisconnectNamedPipe.restype = wintypes.BOOL
    kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel32.CancelIoEx.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    kernel32.LocalFree.restype = wintypes.LPVOID
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        wintypes.LPVOID,
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL


_configure_winapi()


def current_user_sid_string() -> str:
    if not hasattr(ctypes, "windll"):
        return ""

    advapi32 = _advapi32()
    kernel32 = _kernel32()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        return ""

    try:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(needed))
        if not needed.value:
            return ""
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(token, TOKEN_USER, buffer, needed, ctypes.byref(needed)):
            return ""
        token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER_STRUCT)).contents
        sid_text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(token_user.User.Sid, ctypes.byref(sid_text)):
            return ""
        try:
            return sid_text.value or ""
        finally:
            kernel32.LocalFree(ctypes.cast(sid_text, wintypes.LPVOID))
    finally:
        kernel32.CloseHandle(token)


class PipeSecurity:
    def __init__(self, allow_low_integrity_label: bool = False):
        self.security_descriptor = None
        self.attributes = None
        self._allow_low_integrity_label = allow_low_integrity_label
        self._build()

    def _build(self):
        sid = current_user_sid_string()
        if not sid:
            logger.warning("Could not resolve current user SID for TSF pipe security.")
            return

        dacl = f"D:P(A;;GA;;;{sid})(A;;GA;;;SY)(A;;GA;;;BA)"
        sddls = []
        if self._allow_low_integrity_label:
            sddls.append(dacl + "S:(ML;;NW;;;LW)")
        sddls.append(dacl)

        advapi32 = _advapi32()
        for sddl in sddls:
            descriptor = wintypes.LPVOID()
            ok = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                wintypes.LPCWSTR(sddl),
                SDDL_REVISION_1,
                ctypes.byref(descriptor),
                None,
            )
            if ok:
                self.security_descriptor = descriptor
                self.attributes = SECURITY_ATTRIBUTES(
                    ctypes.sizeof(SECURITY_ATTRIBUTES),
                    descriptor,
                    False,
                )
                return
            logger.info("TSF pipe SDDL was rejected; trying a stricter fallback descriptor.")

    def close(self):
        if self.security_descriptor:
            _kernel32().LocalFree(self.security_descriptor)
            self.security_descriptor = None
            self.attributes = None


class NamedPipeHandshakeServer:
    def __init__(
        self,
        pipe_name: str,
        session_id: str,
        nonce: str,
        timeout_ms: int = 100,
        allow_low_integrity_label: bool = False,
    ):
        self.pipe_name = pipe_name
        self.session_id = session_id
        self.nonce = nonce
        self.timeout_ms = max(50, min(150, int(timeout_ms)))
        self.allow_low_integrity_label = allow_low_integrity_label
        self._handle = None
        self._thread = None
        self._done = threading.Event()
        self._result = PipeHandshake(False, "not_started")
        self._security = None

    def run(self) -> PipeHandshake:
        if not hasattr(ctypes, "windll"):
            return PipeHandshake(False, "unsupported", "not_windows")

        self._thread = threading.Thread(target=self._serve_once, name="TSFNamedPipeHandshake", daemon=True)
        self._thread.start()
        if self._done.wait(self.timeout_ms / 1000.0):
            return self._result

        self.close()
        return PipeHandshake(False, "timeout", "handshake_timeout")

    def close(self):
        handle = self._handle
        if handle and handle != INVALID_HANDLE_VALUE:
            try:
                _kernel32().CancelIoEx(handle, None)
            except Exception:
                pass
            try:
                _kernel32().DisconnectNamedPipe(handle)
            except Exception:
                pass
            try:
                _kernel32().CloseHandle(handle)
            except Exception:
                pass
            self._handle = None
        if self._security:
            self._security.close()
            self._security = None

    def _serve_once(self):
        try:
            self._security = PipeSecurity(self.allow_low_integrity_label)
            security_attributes = ctypes.byref(self._security.attributes) if self._security.attributes else None
            self._handle = _kernel32().CreateNamedPipeW(
                wintypes.LPCWSTR(self.pipe_name),
                PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                4096,
                4096,
                self.timeout_ms,
                security_attributes,
            )
            if self._handle == INVALID_HANDLE_VALUE:
                self._result = PipeHandshake(False, "create_failed", f"win32:{_last_error()}")
                return

            connected = _kernel32().ConnectNamedPipe(self._handle, None)
            if not connected and _last_error() != ERROR_PIPE_CONNECTED:
                error = _last_error()
                if error in (ERROR_BROKEN_PIPE,):
                    self._result = PipeHandshake(False, "client_disconnected", f"win32:{error}")
                else:
                    self._result = PipeHandshake(False, "connect_failed", f"win32:{error}")
                return

            request = self._read_message()
            if not request:
                self._result = PipeHandshake(False, "invalid_request", "empty_or_unreadable")
                return
            result = self._validate_request(request)
            self._write_message(
                {
                    "type": "hello_ack",
                    "ok": result.ok,
                    "status": result.status,
                    "reason": result.reason,
                    "session_id": self.session_id,
                }
            )
            self._result = result
        except Exception as e:
            self._result = PipeHandshake(False, "exception", f"{type(e).__name__}:{e}")
        finally:
            self.close()
            self._done.set()

    def _read_message(self) -> dict | None:
        buffer = ctypes.create_string_buffer(MAX_FRAME_BYTES + FRAME_HEADER_BYTES)
        read = wintypes.DWORD()
        ok = _kernel32().ReadFile(self._handle, buffer, len(buffer) - 1, ctypes.byref(read), None)
        if not ok or not read.value:
            return None
        decoded = decode_frame(buffer.raw[: read.value])
        if not decoded.ok:
            logger.info("Rejected malformed TSF IPC frame: status=%s reason=%s", decoded.status, decoded.reason)
            return None
        return decoded.payload

    def _write_message(self, payload: dict):
        data = encode_frame(payload)
        written = wintypes.DWORD()
        _kernel32().WriteFile(self._handle, data, len(data), ctypes.byref(written), None)

    def _validate_request(self, request: dict) -> PipeHandshake:
        if request.get("type") != "hello":
            return PipeHandshake(False, "invalid_request", "wrong_message_type", request)
        if request.get("session_id") != self.session_id:
            return PipeHandshake(False, "invalid_request", "session_mismatch", request)
        if request.get("nonce") != self.nonce:
            return PipeHandshake(False, "invalid_request", "nonce_mismatch", request)
        return PipeHandshake(True, "connected", peer=request)


class NamedPipeCommandSession:
    def __init__(
        self,
        pipe_name: str,
        session_id: str,
        nonce: str,
        timeout_ms: int = 100,
        allow_low_integrity_label: bool = False,
    ):
        self.pipe_name = pipe_name
        self.session_id = session_id
        self.nonce = nonce
        self.timeout_ms = max(50, min(150, int(timeout_ms)))
        self.allow_low_integrity_label = allow_low_integrity_label
        self._handle = None
        self._thread = None
        self._security = None
        self._connected = threading.Event()
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self.result = PipeHandshake(False, "not_started")

    def start(self) -> PipeHandshake:
        if not hasattr(ctypes, "windll"):
            return PipeHandshake(False, "unsupported", "not_windows")
        self._thread = threading.Thread(target=self._serve, name="TSFNamedPipeCommandSession", daemon=True)
        self._thread.start()
        if not self._connected.wait(self.timeout_ms / 1000.0):
            self.close()
            self.result = PipeHandshake(False, "timeout", "handshake_timeout")
        return self.result

    def send(self, payload: dict) -> bool:
        if not self._connected.is_set() or self._closed.is_set():
            return False
        data = encode_frame(payload)
        written = wintypes.DWORD()
        with self._lock:
            if not self._handle:
                return False
            ok = _kernel32().WriteFile(self._handle, data, len(data), ctypes.byref(written), None)
        if not ok or written.value != len(data):
            logger.info("TSF command write failed: win32=%s", _last_error())
            self.close()
            return False
        return True

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        handle = self._handle
        if handle and handle != INVALID_HANDLE_VALUE:
            try:
                _kernel32().CancelIoEx(handle, None)
            except Exception:
                pass
            try:
                _kernel32().DisconnectNamedPipe(handle)
            except Exception:
                pass
            try:
                _kernel32().CloseHandle(handle)
            except Exception:
                pass
            self._handle = None
        if self._security:
            self._security.close()
            self._security = None

    def _serve(self):
        try:
            self._security = PipeSecurity(self.allow_low_integrity_label)
            security_attributes = ctypes.byref(self._security.attributes) if self._security.attributes else None
            self._handle = _kernel32().CreateNamedPipeW(
                wintypes.LPCWSTR(self.pipe_name),
                PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                4096,
                4096,
                self.timeout_ms,
                security_attributes,
            )
            if self._handle == INVALID_HANDLE_VALUE:
                self.result = PipeHandshake(False, "create_failed", f"win32:{_last_error()}")
                self._connected.set()
                return

            connected = _kernel32().ConnectNamedPipe(self._handle, None)
            if not connected and _last_error() != ERROR_PIPE_CONNECTED:
                self.result = PipeHandshake(False, "connect_failed", f"win32:{_last_error()}")
                self._connected.set()
                return

            request = NamedPipeHandshakeServer._read_message(self)  # same handle/framing contract
            if not request:
                self.result = PipeHandshake(False, "invalid_request", "empty_or_unreadable")
                self._connected.set()
                return
            result = NamedPipeHandshakeServer._validate_request(self, request)
            NamedPipeHandshakeServer._write_message(
                self,
                {
                    "type": "hello_ack",
                    "ok": result.ok,
                    "status": result.status,
                    "reason": result.reason,
                    "session_id": self.session_id,
                },
            )
            self.result = result
            self._connected.set()
            if not result.ok:
                return
            while not self._closed.wait(0.25):
                pass
        except Exception as e:
            self.result = PipeHandshake(False, "exception", f"{type(e).__name__}:{e}")
            self._connected.set()
        finally:
            self.close()


def send_test_hello(pipe_name: str, session_id: str, nonce: str, timeout_ms: int = 1000) -> dict:
    deadline = time.monotonic() + max(0.1, timeout_ms / 1000.0)
    last_error = 0
    handle = None
    while time.monotonic() < deadline:
        handle = _kernel32().CreateFileW(
            wintypes.LPCWSTR(pipe_name),
            0xC0000000,  # GENERIC_READ | GENERIC_WRITE
            0,
            None,
            3,  # OPEN_EXISTING
            0,
            None,
        )
        if handle != INVALID_HANDLE_VALUE:
            break
        last_error = _last_error()
        time.sleep(0.01)

    if not handle or handle == INVALID_HANDLE_VALUE:
        return {"ok": False, "status": "connect_failed", "reason": f"win32:{last_error}"}

    try:
        payload = encode_frame({"type": "hello", "session_id": session_id, "nonce": nonce})
        written = wintypes.DWORD()
        if not _kernel32().WriteFile(handle, payload, len(payload), ctypes.byref(written), None):
            return {"ok": False, "status": "write_failed", "reason": f"win32:{_last_error()}"}
        buffer = ctypes.create_string_buffer(MAX_FRAME_BYTES + FRAME_HEADER_BYTES)
        read = wintypes.DWORD()
        if not _kernel32().ReadFile(handle, buffer, len(buffer) - 1, ctypes.byref(read), None):
            return {"ok": False, "status": "read_failed", "reason": f"win32:{_last_error()}"}
        decoded = decode_frame(buffer.raw[: read.value])
        if not decoded.ok:
            return {"ok": False, "status": decoded.status, "reason": decoded.reason}
        return decoded.payload or {"ok": False, "status": "empty_payload"}
    finally:
        _kernel32().CloseHandle(handle)
