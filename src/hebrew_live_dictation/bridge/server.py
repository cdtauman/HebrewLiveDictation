r"""
Named-pipe JSON-RPC server for the WinUI shell <-> engine sidecar boundary.

Transport-only and engine-agnostic: a single-client, overlapped-I/O named pipe
speaking newline-delimited JSON-RPC. Overlapped I/O is required so the engine can
push async events (status/text/error) from any thread while the read loop is blocked
waiting for the next request.

- Pipe:      \\.\pipe\voicetype-bridge   (byte mode, single client, reconnectable)
- Requests:  {"jsonrpc":"2.0","id":N,"method":"...","params":{...}}
- Responses: {"jsonrpc":"2.0","id":N,"result":...} | {"...","error":{...}}
- Events:    {"jsonrpc":"2.0","method":"event","params":{...}}  (no id)

Implemented with ctypes (no pywin32 dependency).
"""

from __future__ import annotations

import ctypes
import json
import logging
import threading
import traceback
from ctypes import wintypes

logger = logging.getLogger("voicetype.bridge.server")

DEFAULT_PIPE_NAME = r"\\.\pipe\voicetype-bridge"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000
ERROR_PIPE_CONNECTED = 535
ERROR_IO_PENDING = 997


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_CreateNamedPipe = kernel32.CreateNamedPipeW
_CreateNamedPipe.restype = wintypes.HANDLE
_CreateNamedPipe.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
]
_ConnectNamedPipe = kernel32.ConnectNamedPipe
_ConnectNamedPipe.restype = wintypes.BOOL
_ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
_ReadFile = kernel32.ReadFile
_ReadFile.restype = wintypes.BOOL
_ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_WriteFile = kernel32.WriteFile
_WriteFile.restype = wintypes.BOOL
_WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                       ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_GetOverlappedResult = kernel32.GetOverlappedResult
_GetOverlappedResult.restype = wintypes.BOOL
_GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                 ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
_CreateEvent = kernel32.CreateEventW
_CreateEvent.restype = wintypes.HANDLE
_CreateEvent.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_ResetEvent = kernel32.ResetEvent
_ResetEvent.argtypes = [wintypes.HANDLE]
_SetEvent = kernel32.SetEvent
_SetEvent.argtypes = [wintypes.HANDLE]
_WaitForMultipleObjects = kernel32.WaitForMultipleObjects
_WaitForMultipleObjects.restype = wintypes.DWORD
_WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD]
_FlushFileBuffers = kernel32.FlushFileBuffers
_FlushFileBuffers.argtypes = [wintypes.HANDLE]
_DisconnectNamedPipe = kernel32.DisconnectNamedPipe
_DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
_CloseHandle = kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]


class NamedPipeJsonRpcServer:
    """Single-client overlapped named-pipe server with thread-safe event push."""

    def __init__(self, on_request, name=DEFAULT_PIPE_NAME):
        self.name = name
        self.on_request = on_request  # (method:str, params:dict) -> result
        self._handle = None
        self._write_lock = threading.Lock()
        self._stop = False
        self._stop_event = _CreateEvent(None, True, False, None)
        self._read_event = _CreateEvent(None, True, False, None)
        self._write_event = _CreateEvent(None, True, False, None)
        self._conn_event = _CreateEvent(None, True, False, None)
        self._thread = threading.Thread(target=self._serve_forever, name="PipeServer", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop = True
        _SetEvent(self._stop_event)
        self._close_handle()

    # -- outbound (server -> client) events, callable from any thread ---------
    def send_event(self, params):
        msg = {"jsonrpc": "2.0", "method": "event", "params": params}
        return self._write_line(json.dumps(msg, ensure_ascii=False))

    def _write_line(self, line):
        data = (line + "\n").encode("utf-8")
        with self._write_lock:
            h = self._handle
            if not h:
                return False
            _ResetEvent(self._write_event)
            ov = OVERLAPPED()
            ov.hEvent = self._write_event
            written = wintypes.DWORD(0)
            ok = _WriteFile(h, data, len(data), None, ctypes.byref(ov))
            if not ok:
                if ctypes.get_last_error() != ERROR_IO_PENDING:
                    return False
                handles = (wintypes.HANDLE * 2)(self._write_event, self._stop_event)
                if _WaitForMultipleObjects(2, handles, False, INFINITE) != WAIT_OBJECT_0:
                    return False
                if not _GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(written), False):
                    return False
            return True

    def _close_handle(self):
        h, self._handle = self._handle, None
        if h:
            try:
                _FlushFileBuffers(h)
                _DisconnectNamedPipe(h)
                _CloseHandle(h)
            except Exception:
                pass

    def _serve_forever(self):
        while not self._stop:
            h = _CreateNamedPipe(
                self.name,
                PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES, 65536, 65536, 0, None,
            )
            if h == INVALID_HANDLE_VALUE or h is None:
                logger.error("CreateNamedPipe failed: %s", ctypes.get_last_error())
                return
            if not self._wait_connect(h):
                _CloseHandle(h)
                if self._stop:
                    return
                continue
            self._handle = h
            logger.info("Pipe client connected.")
            try:
                self._read_loop(h)
            except Exception:
                logger.error("pipe read loop error:\n%s", traceback.format_exc())
            finally:
                self._close_handle()
                logger.info("Pipe client disconnected.")

    def _wait_connect(self, h):
        _ResetEvent(self._conn_event)
        ov = OVERLAPPED()
        ov.hEvent = self._conn_event
        ok = _ConnectNamedPipe(h, ctypes.byref(ov))
        if ok:
            return True
        err = ctypes.get_last_error()
        if err == ERROR_PIPE_CONNECTED:
            return True
        if err != ERROR_IO_PENDING:
            return False
        handles = (wintypes.HANDLE * 2)(self._conn_event, self._stop_event)
        return _WaitForMultipleObjects(2, handles, False, INFINITE) == WAIT_OBJECT_0 and not self._stop

    def _read_loop(self, h):
        buf = ctypes.create_string_buffer(65536)
        nread = wintypes.DWORD(0)
        pending = b""
        while not self._stop:
            _ResetEvent(self._read_event)
            ov = OVERLAPPED()
            ov.hEvent = self._read_event
            ok = _ReadFile(h, buf, 65536, None, ctypes.byref(ov))
            if not ok:
                if ctypes.get_last_error() != ERROR_IO_PENDING:
                    break  # broken pipe / client gone
                handles = (wintypes.HANDLE * 2)(self._read_event, self._stop_event)
                if _WaitForMultipleObjects(2, handles, False, INFINITE) != WAIT_OBJECT_0:
                    break  # stopping
            if not _GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(nread), False):
                break
            if nread.value == 0:
                break
            pending += buf.raw[: nread.value]
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                line = line.strip()
                if line:
                    self._dispatch(line.decode("utf-8", errors="replace"))

    def _dispatch(self, line):
        try:
            req = json.loads(line)
        except Exception:
            return
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        try:
            result = self.on_request(method, params)
            if rid is not None:
                self._write_line(json.dumps(
                    {"jsonrpc": "2.0", "id": rid, "result": result}, ensure_ascii=False))
        except Exception as e:
            logger.error("RPC method %s failed: %s", method, e)
            if rid is not None:
                self._write_line(json.dumps(
                    {"jsonrpc": "2.0", "id": rid,
                     "error": {"code": -32000, "message": str(e)}}, ensure_ascii=False))
