"""Desktop IPC listener; stdout contains metrics only, never conversation text."""
import argparse
import ctypes
import json
import msvcrt
import os
from pathlib import Path
import struct
import sys
import time
import uuid
from collections import deque

import read_status


class SpeedMeter:
    def __init__(self, encode):
        self.encode = encode
        self.reset()

    def reset(self):
        self.items = {}
        self.samples = deque()
        self.started = None
        self.last_text = None
        self.revision = None
        self.pending = {}
        self.last_speed = None

    def remember(self, value, path=()):
        if isinstance(value, dict):
            if value.get("type") == "agentMessage" and isinstance(value.get("text"), str):
                self.items[path] = (value["text"], len(self.encode(value["text"])))
                return
            for key, child in value.items():
                self.remember(child, path + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self.remember(child, path + (index,))

    def apply(self, change, now):
        if change.get("type") == "snapshot":
            self.reset()
            self.remember(change.get("conversationState", {}))
            self.revision = change.get("revision")
            return
        if change.get("type") != "patches" or change.get("baseRevision") != self.revision:
            raise ValueError("Stream revision mismatch")
        self.revision = change.get("revision")
        for patch in change.get("patches", []):
            path = tuple(patch.get("path", []))
            value = patch.get("value")
            if path and path[-1] == "text" and path[:-1] in self.items and isinstance(value, str):
                parent = path[:-1]
                previous = self.pending.get(parent, self.items[parent][0])
                # Hydration, replacement and repeated text must not count as output.
                if value.startswith(previous) and len(value) > len(previous):
                    if self.last_text is None or now - self.last_text > 3:
                        self.samples.clear()
                        self.started = now
                    self.last_text = now
                    self.pending[parent] = value
                else:
                    self.items[parent] = (value, len(self.encode(value)))
                    self.pending.pop(parent, None)
            elif isinstance(value, dict) and value.get("type") == "agentMessage" and path in self.items:
                # Completion may replace an entire item before the next sample.
                # Preserve the queued increment instead of resetting its baseline.
                text = value.get("text")
                if isinstance(text, str):
                    previous = self.pending.get(path, self.items[path][0])
                    if text.startswith(previous):
                        self.pending[path] = text
                    else:
                        self.pending.pop(path, None)
                        self.items[path] = (text, len(self.encode(text)))
            elif isinstance(value, (dict, list)):
                self.remember(value, path)
            if patch.get("op") == "remove":
                for item in list(self.items):
                    if item[:len(path)] == path:
                        self.items.pop(item, None)
                        self.pending.pop(item, None)

    def metric(self, now):
        delta = 0
        for path, text in self.pending.items():
            count = len(self.encode(text))
            delta += count - self.items[path][1]
            self.items[path] = (text, count)
        self.pending.clear()
        if delta:
            self.samples.append((now, delta))
        while self.samples and now - self.samples[0][0] > 5:
            self.samples.popleft()
        if self.last_text is None or now - self.last_text > 3:
            return {"status": "idle", "tokens_per_second": self.last_speed}
        elapsed = min(5, now - self.started)
        if elapsed < 0.5:
            return {"status": "warming", "tokens_per_second": self.last_speed}
        speed = round(max(0, sum(n for _, n in self.samples)) / elapsed, 1)
        # A tool pause must not gradually lower the last visible output speed.
        if speed > 0 and (delta > 0 or self.last_speed is None):
            self.last_speed = speed
        return {"status": "streaming", "tokens_per_second": self.last_speed}


def emit(thread_id, metric):
    read_status.emit({"thread_id": thread_id, "estimated": True,
                      "encoding": "o200k_base", **metric})
    sys.stdout.write("\n")
    sys.stdout.flush()


def run(parent_pid, selected_thread=None):
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "dependencies"))
    os.environ["TIKTOKEN_CACHE_DIR"] = str(root / "tokenizer-cache")
    # Never fetch missing tokenizer files in a background UI process.
    import tiktoken
    from tiktoken.load import read_file
    import tiktoken.load
    def offline_read(path):
        if path.startswith(("http://", "https://")):
            raise RuntimeError("Local tokenizer cache missing")
        return read_file(path)
    tiktoken.load.read_file = offline_read
    encoding = tiktoken.get_encoding("o200k_base")
    meter = SpeedMeter(lambda text: encoding.encode(text, disallowed_special=()))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.PeekNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    parent = kernel.OpenProcess(0x100000, False, parent_pid)
    if not parent:
        raise ctypes.WinError(ctypes.get_last_error())
    def alive():
        return kernel.WaitForSingleObject(parent, 0) == 258
    try:
        while alive():
            thread_id = None
            try:
                with open(r"\\.\pipe\codex-ipc", "r+b", buffering=0) as pipe:
                    handle = msvcrt.get_osfhandle(pipe.fileno())
                    client_id = "initializing-client"
                    buffer = bytearray()
                    last_poll = last_emit = 0
                    connected_at = time.monotonic()
                    initialized = False
                    def send(message):
                        body = json.dumps(message).encode("utf-8")
                        frame = struct.pack("<I", len(body)) + body
                        while frame:
                            written = pipe.write(frame)
                            if not written:
                                raise OSError("IPC write failed")
                            frame = frame[written:]
                    def follow(target, value):
                        if target:
                            send({"type": "broadcast", "method": "thread-stream-following-changed",
                                  "sourceClientId": client_id, "version": 1,
                                  "params": {"hostId": "local", "conversationId": target, "following": value}})
                    send({"type": "request", "requestId": str(uuid.uuid4()), "sourceClientId": client_id,
                          "version": 0, "method": "initialize", "params": {"clientType": "codex-status-speed"}})
                    try:
                        while alive():
                            now = time.monotonic()
                            if not initialized and now - connected_at > 5:
                                raise TimeoutError("IPC initialization timed out")
                            if initialized and now - last_poll >= 1:
                                selected = selected_thread or read_status.active_thread_id_from_logs()
                                if selected != thread_id:
                                    follow(thread_id, False)
                                    thread_id = selected
                                    meter.reset()
                                    follow(thread_id, True)
                                last_poll = now
                            available = ctypes.c_uint32()
                            if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                                raise ctypes.WinError(ctypes.get_last_error())
                            if available.value:
                                buffer.extend(pipe.read(min(available.value, 1048576)))
                            while len(buffer) >= 4:
                                length = struct.unpack_from("<I", buffer)[0]
                                if not 0 < length <= 268435456:
                                    raise ValueError("Invalid IPC frame")
                                if len(buffer) < length + 4:
                                    break
                                message = json.loads(buffer[4:length + 4])
                                del buffer[:length + 4]
                                method = message.get("method")
                                if method == "initialize" and message.get("resultType") == "success":
                                    client_id = message["result"]["clientId"]
                                    initialized = True
                                elif message.get("type") == "client-discovery-request":
                                    send({"type": "client-discovery-response", "requestId": message["requestId"],
                                          "response": {"canHandle": False}})
                                elif method == "thread-stream-state-changed":
                                    params = message.get("params", {})
                                    if params.get("conversationId") == thread_id:
                                        if message.get("version") != 11:
                                            raise ValueError("Unsupported IPC stream version")
                                        meter.apply(params.get("change", {}), now)
                            if now - last_emit >= 0.5:
                                emit(thread_id, meter.metric(now) if initialized and meter.revision is not None
                                     else {"status": "connecting", "tokens_per_second": None})
                                last_emit = now
                            time.sleep(0.05)
                    finally:
                        try:
                            follow(thread_id, False)
                        except OSError:
                            pass
            except (OSError, ValueError, TimeoutError):
                emit(thread_id, {"status": "unavailable", "tokens_per_second": None})
                end = time.monotonic() + 3
                while alive() and time.monotonic() < end:
                    time.sleep(0.1)
    finally:
        kernel.CloseHandle(parent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--thread-id", help="Pin one thread for read-only diagnostics")
    args = parser.parse_args()
    try:
        run(args.parent_pid, args.thread_id)
    except Exception:
        emit(None, {"status": "unavailable", "tokens_per_second": None})
        sys.exit(1)
