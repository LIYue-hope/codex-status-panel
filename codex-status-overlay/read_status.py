import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


def emit(payload):
    # Keep the process boundary ASCII-only. Windows PowerShell/.NET hosts can
    # otherwise decode redirected UTF-8 with the active legacy code page,
    # which turns Chinese task titles into mojibake before ConvertFrom-Json
    # ever sees them. JSON restores these escapes to the original Unicode.
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def reverse_lines(path, chunk_size=65536):
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        remainder = b""
        while position > 0:
            size = min(chunk_size, position)
            position -= size
            handle.seek(position)
            block = handle.read(size) + remainder
            lines = block.split(b"\n")
            remainder = lines[0]
            for line in reversed(lines[1:]):
                if line.strip():
                    yield line
        if remainder.strip():
            yield remainder


def latest_token_event(rollout_path, require_rate_limits=False):
    path = Path(rollout_path)
    if not path.is_file():
        return None
    for raw_line in reverse_lines(path):
        try:
            record = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        payload = record.get("payload") or {}
        if record.get("type") == "event_msg" and payload.get("type") == "token_count":
            if require_rate_limits and not (payload.get("rate_limits") or {}):
                continue
            return {"timestamp": record.get("timestamp"), "payload": payload}
    return None


def latest_rate_limit_event(rollout_paths):
    """Find the newest account-limit snapshot, independent of selected task."""
    newest = None
    for rollout_path in rollout_paths:
        event = latest_token_event(rollout_path, require_rate_limits=True)
        if event is None:
            continue
        if newest is None or (event.get("timestamp") or "") > (newest.get("timestamp") or ""):
            newest = event
    return newest


def active_window_title():
    helper = Path(__file__).with_name("get_active_codex_title.exe")
    if not helper.is_file():
        return None
    try:
        completed = subprocess.run(
            [str(helper)],
            capture_output=True,
            timeout=1.5,
            check=False,
        )
        if completed.returncode == 0:
            title = completed.stdout.decode("utf-8", errors="replace").strip()
            return title or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


THREAD_ID_PATTERN = rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ACTIVE_VIEW_RE = re.compile(rb"\bconversationId=(" + THREAD_ID_PATTERN + rb")\b")
ACTIVE_ROUTE_RE = re.compile(rb"\bownerRoutePath=/local/(" + THREAD_ID_PATTERN + rb")\b")


def codex_desktop_logs():
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    log_dirs = [local_app_data / "Codex" / "Logs"]
    packages = local_app_data / "Packages"
    if packages.is_dir():
        for package in packages.glob("OpenAI.Codex_*"):
            log_dirs.append(package / "LocalCache" / "Local" / "Codex" / "Logs")

    files = []
    for log_dir in log_dirs:
        if not log_dir.is_dir():
            continue
        files.extend(path for path in log_dir.rglob("*.log") if path.is_file())
    try:
        return sorted(files, key=lambda path: path.stat().st_mtime_ns, reverse=True)
    except OSError:
        return files


def active_thread_id_from_logs():
    """Return the task currently shown by the focused primary Codex window.

    Recent Codex desktop builds no longer expose the web contents through
    MSAA/UI Automation. They do, however, log every primary-window route
    change and active thread view. Reading backwards makes this both exact and
    cheap while preserving the recency fallback for older builds.
    """
    for log_path in codex_desktop_logs():
        try:
            for raw_line in reverse_lines(log_path):
                if (
                    b"thread_stream_view_activity_changed" in raw_line
                    and b"active=true" in raw_line
                    and b"rendererWindowAppearance=primary" in raw_line
                    and b"rendererWindowFocused=true" in raw_line
                ):
                    match = ACTIVE_VIEW_RE.search(raw_line)
                    if match:
                        return match.group(1).decode("ascii")
                if b"ownerRoutePath=/local/" in raw_line:
                    match = ACTIVE_ROUTE_RE.search(raw_line)
                    if match:
                        return match.group(1).decode("ascii")
        except OSError:
            continue
    return None


def clean_display_title(selected_title, stored_title, selection_source):
    title = selected_title if selection_source == "window_accessibility" else stored_title
    title = (title or "").strip()
    if not title or "\ufffd" in title or "���" in title:
        return "未命名任务"
    return title


def main():
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    state_path = codex_home / "state_5.sqlite"
    if not state_path.is_file():
        emit({"ok": False, "error": "未找到 Codex 状态数据库"})
        return 2

    selected_thread_id = active_thread_id_from_logs()
    selected_title = None
    selection_source = "desktop_activity_log" if selected_thread_id else "recency_fallback"
    connection = sqlite3.connect(f"file:{state_path.as_posix()}?mode=ro", uri=True, timeout=1)
    try:
        row = None
        limit_rollout_paths = []
        if selected_thread_id:
            row = connection.execute(
                """
                SELECT id, COALESCE(name, title), cwd, rollout_path, model, recency_at_ms
                FROM threads
                WHERE id = ? AND archived = 0 AND thread_source = 'user'
                LIMIT 1
                """,
                (selected_thread_id,),
            ).fetchone()
        if row is None:
            selected_title = active_window_title()
        if row is None and selected_title:
            selection_source = "window_accessibility"
            row = connection.execute(
                """
                SELECT id, COALESCE(name, title), cwd, rollout_path, model, recency_at_ms
                FROM threads
                WHERE archived = 0 AND thread_source = 'user'
                  AND (name = ? OR title = ?)
                ORDER BY recency_at_ms DESC
                LIMIT 1
                """,
                (selected_title, selected_title),
            ).fetchone()
        if row is None:
            selection_source = "recency_fallback"
            row = connection.execute(
                """
                SELECT id, COALESCE(name, title), cwd, rollout_path, model, recency_at_ms
                FROM threads
                WHERE archived = 0 AND thread_source = 'user'
                ORDER BY recency_at_ms DESC
                LIMIT 1
                """
            ).fetchone()
        limit_rollout_paths = [
            item[0]
            for item in connection.execute(
                """
                SELECT rollout_path
                FROM threads
                WHERE thread_source = 'user' AND rollout_path IS NOT NULL AND rollout_path != ''
                ORDER BY recency_at_ms DESC
                LIMIT 64
                """
            ).fetchall()
        ]
    finally:
        connection.close()

    if row is None:
        emit({"ok": False, "error": "没有找到活动的 Codex 任务"})
        return 3

    thread_id, title, cwd, rollout_path, model, recency_at_ms = row
    title = clean_display_title(selected_title, title, selection_source)
    context_event = latest_token_event(rollout_path)
    limits_event = latest_rate_limit_event(limit_rollout_paths)
    result = {
        "ok": True,
        "thread": {
            "id": thread_id,
            "title": title or "未命名任务",
            "cwd": cwd or "",
            "model": model or "未知模型",
            "recency_at_ms": recency_at_ms,
            "selection_source": selection_source,
        },
        "context": None,
        "limits": [],
    }

    if context_event:
        payload = context_event["payload"]
        info = payload.get("info") or {}
        last_usage = info.get("last_token_usage") or {}
        context_window = info.get("model_context_window")
        context_tokens = last_usage.get("total_tokens")
        if isinstance(context_tokens, (int, float)) and isinstance(context_window, (int, float)) and context_window > 0:
            result["context"] = {
                "tokens": int(context_tokens),
                "window": int(context_window),
                "percent": round(context_tokens * 100.0 / context_window, 1),
                "input_tokens": int(last_usage.get("input_tokens") or 0),
                "output_tokens": int(last_usage.get("output_tokens") or 0),
                "timestamp": context_event.get("timestamp"),
            }

    if limits_event:
        payload = limits_event["payload"]
        rate_limits = payload.get("rate_limits") or {}
        for key in ("primary", "secondary"):
            window = rate_limits.get(key) or {}
            minutes = window.get("window_minutes")
            if not isinstance(minutes, (int, float)):
                continue
            label = "5 小时" if int(minutes) == 300 else ("一周" if int(minutes) == 10080 else f"{int(minutes)} 分钟")
            result["limits"].append(
                {
                    "label": label,
                    "window_minutes": int(minutes),
                    "used_percent": float(window.get("used_percent") or 0),
                    "resets_at": window.get("resets_at"),
                }
            )

    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
