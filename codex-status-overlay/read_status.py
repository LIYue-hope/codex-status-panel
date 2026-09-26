import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from queue import Empty, Queue
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path


HISTORY_SCHEMA_VERSION = "1"
ROLLOUT_ID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


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


def history_database_path():
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".codex-status-panel"
    return root / "CodexStatusPanel" / "usage-history.sqlite" if local_app_data else root / "usage-history.sqlite"


def rollout_files(codex_home):
    paths = []
    for directory_name in ("sessions", "archived_sessions"):
        directory = codex_home / directory_name
        if directory.is_dir():
            paths.extend(directory.rglob("rollout-*.jsonl"))
    return [path for path in paths if path.is_file()]


def open_history_database(codex_home, now=None):
    database_path = history_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path), timeout=3)
    connection.execute("PRAGMA busy_timeout = 3000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sources (
            path TEXT PRIMARY KEY,
            byte_offset INTEGER NOT NULL,
            file_size INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage_events (
            event_key TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            occurred_at REAL NOT NULL,
            input_tokens INTEGER NOT NULL,
            cached_input_tokens INTEGER NOT NULL,
            cache_write_input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            reasoning_output_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS usage_events_occurred_at
            ON usage_events(occurred_at);
        CREATE TABLE IF NOT EXISTS seen_events (
            event_key TEXT PRIMARY KEY
        );
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO seen_events(event_key) SELECT event_key FROM usage_events"
    )
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'installed_at'"
    ).fetchone()
    created = row is None
    if created:
        installed_at = float(now if now is not None else time.time())
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('installed_at', ?)",
            (str(installed_at),),
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
            (HISTORY_SCHEMA_VERSION,),
        )
        # Existing rollouts form the installation baseline. Only bytes appended
        # after this point are eligible for history, so pre-install usage is
        # never silently imported.
        for path in rollout_files(codex_home):
            try:
                stat = path.stat()
            except OSError:
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO sources(path, byte_offset, file_size, modified_ns)
                VALUES(?, ?, ?, ?)
                """,
                (str(path), stat.st_size, stat.st_size, stat.st_mtime_ns),
            )
            baseline_record = latest_token_event(path)
            if baseline_record is not None:
                match = ROLLOUT_ID_RE.search(path.name)
                thread_id = match.group(1).lower() if match else hashlib.sha1(str(path).encode("utf-8")).hexdigest()
                baseline_event = usage_event_from_record(baseline_record, thread_id, str(path))
                if baseline_event is not None:
                    connection.execute(
                        "INSERT OR IGNORE INTO seen_events(event_key) VALUES(?)",
                        (baseline_event[0],),
                    )
        connection.commit()
    else:
        installed_at = float(row[0])
    return connection, database_path, installed_at, created


def parse_event_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def usage_event_from_record(record, thread_id, source_path):
    payload = record.get("payload") or {}
    if record.get("type") != "event_msg" or payload.get("type") != "token_count":
        return None
    info = payload.get("info") or {}
    usage = info.get("last_token_usage") or {}
    cumulative_usage = info.get("total_token_usage") or {}
    occurred_at = parse_event_timestamp(record.get("timestamp"))
    if occurred_at is None or not isinstance(usage, dict) or not usage:
        return None

    def token_value(name):
        value = usage.get(name)
        return max(0, int(value)) if isinstance(value, (int, float)) else 0

    input_tokens = token_value("input_tokens")
    output_tokens = token_value("output_tokens")
    total_tokens = token_value("total_tokens") or input_tokens + output_tokens
    if isinstance(cumulative_usage, dict) and cumulative_usage:
        # The same token snapshot can be emitted again with a new ordinal when
        # only surrounding status changes. Its cumulative counters are stable,
        # so keying on them prevents double-counting that model call.
        cumulative_identity = json.dumps(cumulative_usage, sort_keys=True, separators=(",", ":"))
        event_key = hashlib.sha256(f"{thread_id}\0{cumulative_identity}".encode("utf-8")).hexdigest()
    elif isinstance(record.get("ordinal"), int):
        ordinal = record["ordinal"]
        event_key = f"{thread_id}:{ordinal}"
    else:
        identity = f"{source_path}\0{record.get('timestamp')}\0{json.dumps(usage, sort_keys=True)}"
        event_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return (
        event_key,
        thread_id,
        occurred_at,
        input_tokens,
        token_value("cached_input_tokens"),
        token_value("cache_write_input_tokens"),
        output_tokens,
        token_value("reasoning_output_tokens"),
        total_tokens,
    )


def sync_usage_history(connection, codex_home, installed_at):
    inserted = 0
    for path in rollout_files(codex_home):
        path_text = str(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        row = connection.execute(
            "SELECT byte_offset, file_size, modified_ns FROM sources WHERE path = ?",
            (path_text,),
        ).fetchone()
        if row and row[1] == stat.st_size and row[2] == stat.st_mtime_ns:
            continue
        offset = int(row[0]) if row else 0
        if offset < 0 or offset > stat.st_size:
            offset = 0
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                new_bytes = handle.read()
        except OSError:
            continue

        # Keep an incomplete final JSONL record for the next sync instead of
        # advancing past it and permanently losing that usage event.
        complete_length = len(new_bytes)
        if new_bytes and not new_bytes.endswith(b"\n"):
            last_newline = new_bytes.rfind(b"\n")
            complete_length = last_newline + 1 if last_newline >= 0 else 0
        completed = new_bytes[:complete_length]
        match = ROLLOUT_ID_RE.search(path.name)
        thread_id = match.group(1).lower() if match else hashlib.sha1(path_text.encode("utf-8")).hexdigest()
        for raw_line in completed.splitlines():
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            event = usage_event_from_record(record, thread_id, path_text)
            if event is None or event[2] < installed_at:
                continue
            seen_cursor = connection.execute(
                "INSERT OR IGNORE INTO seen_events(event_key) VALUES(?)",
                (event[0],),
            )
            if seen_cursor.rowcount == 0:
                continue
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO usage_events(
                    event_key, thread_id, occurred_at, input_tokens,
                    cached_input_tokens, cache_write_input_tokens, output_tokens,
                    reasoning_output_tokens, total_tokens
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                event,
            )
            inserted += max(0, cursor.rowcount)
        connection.execute(
            """
            INSERT OR REPLACE INTO sources(path, byte_offset, file_size, modified_ns)
            VALUES(?, ?, ?, ?)
            """,
            (path_text, offset + complete_length, stat.st_size, stat.st_mtime_ns),
        )
    connection.commit()
    return inserted


def usage_history_summary(connection, installed_at, start_epoch=None, end_epoch=None):
    now = time.time()
    start = max(installed_at, float(start_epoch if start_epoch is not None else installed_at))
    end = float(end_epoch if end_epoch is not None else now)
    if end < start:
        start, end = end, start
        start = max(installed_at, start)
    row = connection.execute(
        """
        SELECT COUNT(*),
               COALESCE(SUM(input_tokens), 0),
               COALESCE(SUM(cached_input_tokens), 0),
               COALESCE(SUM(cache_write_input_tokens), 0),
               COALESCE(SUM(output_tokens), 0),
               COALESCE(SUM(reasoning_output_tokens), 0),
               COALESCE(SUM(total_tokens), 0),
               MAX(occurred_at)
        FROM usage_events
        WHERE occurred_at >= ? AND occurred_at < ?
        """,
        (start, end),
    ).fetchone()
    return {
        "installed_at": installed_at,
        "range_start": start,
        "range_end": end,
        "event_count": int(row[0]),
        "input_tokens": int(row[1]),
        "cached_input_tokens": int(row[2]),
        "cache_write_input_tokens": int(row[3]),
        "output_tokens": int(row[4]),
        "reasoning_output_tokens": int(row[5]),
        "total_tokens": int(row[6]),
        "last_event_at": row[7],
    }


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
            return {
                "timestamp": record.get("timestamp"),
                "ordinal": record.get("ordinal"),
                "type": record.get("type"),
                "payload": payload,
            }
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


def reset_credit_count(rate_limits):
    """Return the available reset-card count from a rate-limit snapshot."""
    credits = rate_limits.get("credits") if isinstance(rate_limits, dict) else None
    if not isinstance(credits, dict) or credits.get("has_credits") is False:
        return 0

    balance = credits.get("balance")
    if isinstance(balance, bool) or balance is None:
        return 0
    try:
        count = int(Decimal(str(balance)))
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return 0
    return max(0, count)


def app_server_command():
    """Prefer the complete app-server binary bundled with Codex Desktop."""
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    desktop_bin = local_app_data / "OpenAI" / "Codex" / "bin"
    candidates = [path for path in desktop_bin.glob("*/codex.exe") if path.is_file()]
    if candidates:
        latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
        return [str(latest), "app-server", "--stdio"]
    # Older installations may instead expose a managed app-server daemon.
    return ["codex", "app-server", "proxy"]


def app_server_response_queue(stream):
    """Copy an app-server stream into one queue shared by the full RPC session."""
    lines = Queue()

    def copy_lines():
        for line in iter(stream.readline, ""):
            lines.put(line)

    threading.Thread(target=copy_lines, daemon=True).start()
    return lines


def read_app_server_response(lines, request_id, timeout_seconds=4):
    """Read a JSON-RPC response without allowing a dead app-server to hang UI refreshes."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Codex 本地 app-server 响应超时")
        try:
            line = lines.get(timeout=remaining)
        except Empty as error:
            raise TimeoutError("Codex 本地 app-server 响应超时") from error
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if response.get("id") == request_id:
            return response


def read_live_reset_credit_count():
    """Read the account's banked reset count through Codex's local app server."""
    messages = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "codex-status-overlay", "version": "1.0"},
                "capabilities": {},
            },
        },
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "account/rateLimits/read",
            # Background polls only need the aggregate count, not the credit
            # titles, IDs, descriptions, or expiry details.
            "params": {"excludeResetCreditDetails": True},
        },
    )
    try:
        process = subprocess.Popen(
            app_server_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None, "无法启动 Codex 本地 app-server"

    try:
        assert process.stdin is not None and process.stdout is not None

        def send(message):
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()

        responses = app_server_response_queue(process.stdout)
        send(messages[0])
        initialization = read_app_server_response(responses, 1)
        if "error" in initialization:
            return None, "Codex 本地 app-server 初始化失败"
        send(messages[1])
        send(messages[2])
        response = read_app_server_response(responses, 2)
        if "error" in response:
            return None, "实时账户查询被拒绝"
        summary = (response.get("result") or {}).get("rateLimitResetCredits")
        if not isinstance(summary, dict):
            return None, "实时账户响应未包含重置卡数量"
        count = summary.get("availableCount")
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            return None, "实时账户响应中的重置卡数量无效"
        return max(0, int(count)), None
    except (OSError, TimeoutError, ValueError):
        return None, "无法连接 Codex 本地 app-server"
    finally:
        try:
            process.stdin.close()
        except (AttributeError, OSError):
            pass
        try:
            process.terminate()
            process.wait(timeout=1)
        except (AttributeError, OSError, subprocess.SubprocessError):
            pass


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


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="Read Codex status and locally recorded token history.")
    parser.add_argument("--initialize-history", action="store_true")
    parser.add_argument("--history-start", type=float)
    parser.add_argument("--history-end", type=float)
    parser.add_argument("--read-live-reset-credits", action="store_true")
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="Skip history database synchronization for this lightweight status poll.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_arguments(argv)
    if args.initialize_history:
        args.skip_history = False
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    history = None
    history_error = None
    history_path = None
    if not args.skip_history:
        try:
            history_connection, history_path, installed_at, history_created = open_history_database(codex_home)
            try:
                imported_events = sync_usage_history(history_connection, codex_home, installed_at)
                history = usage_history_summary(
                    history_connection,
                    installed_at,
                    args.history_start,
                    args.history_end,
                )
            finally:
                history_connection.close()
        except (OSError, sqlite3.Error, ValueError) as error:
            history_created = False
            imported_events = 0
            history_error = str(error)

    if args.initialize_history:
        if history_error:
            emit({"ok": False, "error": f"历史用量初始化失败：{history_error}"})
            return 4
        emit(
            {
                "ok": True,
                "history_database": str(history_path),
                "installed_at": history["installed_at"],
                "created": history_created,
                "imported_events": imported_events,
            }
        )
        return 0

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
        "reset_credits": 0,
        "reset_credits_source": "local_snapshot",
        "live_reset_credits_error": None,
        "history": history,
        "history_error": history_error,
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
        result["reset_credits"] = reset_credit_count(rate_limits)
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

    if args.read_live_reset_credits:
        live_count, live_error = read_live_reset_credit_count()
        if live_count is None:
            result["reset_credits_source"] = "live_account_unavailable"
            result["live_reset_credits_error"] = live_error
        else:
            result["reset_credits"] = live_count
            result["reset_credits_source"] = "live_account"

    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
