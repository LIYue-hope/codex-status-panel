"""Read-only desktop IPC probe. Prints metadata, never message contents."""
import ctypes
import json
import msvcrt
import struct
import time
import uuid
from collections import Counter

import read_status


def main():
    thread_id = read_status.active_thread_id_from_logs()
    if not thread_id:
        raise RuntimeError("No active desktop thread found")
    counts = Counter()
    client_id = "initializing-client"
    buffer = bytearray()
    subscribed = False
    peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
    peek.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                     ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    peek.restype = ctypes.c_int
    with open(r"\\.\pipe\codex-ipc", "r+b", buffering=0) as pipe:
        handle = msvcrt.get_osfhandle(pipe.fileno())

        def send(message):
            body = json.dumps(message).encode("utf-8")
            pipe.write(struct.pack("<I", len(body)) + body)

        def following(value):
            send({"type": "broadcast", "method": "thread-stream-following-changed",
                  "sourceClientId": client_id, "version": 1,
                  "params": {"hostId": "local", "conversationId": thread_id,
                             "following": value}})

        send({"type": "request", "requestId": str(uuid.uuid4()),
              "sourceClientId": client_id, "version": 0, "method": "initialize",
              "params": {"clientType": "codex-status-probe"}})
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                available = ctypes.c_uint32()
                if not peek(handle, None, 0, None, ctypes.byref(available), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not available.value:
                    time.sleep(0.05)
                    continue
                buffer.extend(pipe.read(available.value))
                while len(buffer) >= 4:
                    length = struct.unpack_from("<I", buffer)[0]
                    if not 0 < length <= 268435456:
                        raise ValueError("Invalid IPC frame length")
                    if len(buffer) < length + 4:
                        break
                    message = json.loads(buffer[4:length + 4])
                    del buffer[:length + 4]
                    method = message.get("method", message.get("type", "unknown"))
                    counts[method] += 1
                    if method == "initialize" and message.get("resultType") == "success":
                        client_id = message["result"]["clientId"]
                        print("IPC initialization succeeded", flush=True)
                        following(True)
                        subscribed = True
                    if message.get("type") == "client-discovery-request":
                        send({"type": "client-discovery-response",
                              "requestId": message["requestId"],
                              "response": {"canHandle": False}})
                    if method == "thread-stream-state-changed":
                        params = message.get("params", {})
                        if params.get("conversationId") != thread_id:
                            continue
                        change = params.get("change", {})
                        if change.get("type") == "snapshot":
                            print("Snapshot keys:", sorted(change.get("conversationState", {})), flush=True)
                        else:
                            paths = [p.get("path") for p in change.get("patches", [])]
                            for patch in change.get("patches", []):
                                if patch.get("path") == ["latestTokenUsageInfo"]:
                                    print("Usage event:", patch.get("value"), flush=True)
                            edits = change.get("acceptedTextChanges") or []
                            if edits and counts.get("text_schema", 0) == 0:
                                def shape(value):
                                    if isinstance(value, dict):
                                        return {k: shape(v) for k, v in value.items()}
                                    if isinstance(value, list):
                                        return [shape(v) for v in value[:1]]
                                    return type(value).__name__
                                print("Text change schema:", shape(edits[0]), flush=True)
                                print("Text edit metadata:", {k: v for k, v in edits[0].items()
                                                             if k in ("type", "field", "at")}, flush=True)
                                counts["text_schema"] += 1
                            counts["text_updates"] += len(edits)
            print("Event counts:", dict(counts), flush=True)
        finally:
            if subscribed:
                following(False)


if __name__ == "__main__":
    main()
