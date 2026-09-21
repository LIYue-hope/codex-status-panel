import importlib.util
import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "read_status.py"
SPEC = importlib.util.spec_from_file_location("read_status", MODULE_PATH)
read_status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(read_status)


def token_event(ordinal, timestamp, cumulative_total=None, **overrides):
    usage = {
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "cache_write_input_tokens": 5,
        "output_tokens": 20,
        "reasoning_output_tokens": 7,
        "total_tokens": 120,
    }
    usage.update(overrides)
    total_usage = dict(usage)
    if cumulative_total is not None:
        total_usage["total_tokens"] = cumulative_total
        total_usage["input_tokens"] = cumulative_total - total_usage["output_tokens"]
    return {
        "timestamp": timestamp,
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"last_token_usage": usage, "total_token_usage": total_usage},
        },
    }


class UsageHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = Path(__file__).resolve().parent / ".tmp"
        temporary_parent.mkdir(exist_ok=True)
        self.root = temporary_parent / str(uuid.uuid4())
        self.root.mkdir()
        self.codex_home = self.root / ".codex"
        self.sessions = self.codex_home / "sessions" / "2026" / "01" / "01"
        self.sessions.mkdir(parents=True)
        self.rollout = self.sessions / "rollout-2026-01-01T00-00-00-11111111-1111-1111-1111-111111111111.jsonl"
        self.rollout.write_text(json.dumps(token_event(1, "2026-01-01T00:00:00Z")) + "\n", encoding="utf-8")
        self.environment = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_baseline_excludes_existing_usage_and_counts_appended_events_once(self):
        connection, _, installed_at, created = read_status.open_history_database(
            self.codex_home, now=1767225601
        )
        self.assertTrue(created)
        self.assertEqual(read_status.sync_usage_history(connection, self.codex_home, installed_at), 0)

        with self.rollout.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(token_event(2, "2026-01-01T00:00:02Z", 240)) + "\n")
        self.assertEqual(read_status.sync_usage_history(connection, self.codex_home, installed_at), 1)
        self.assertEqual(read_status.sync_usage_history(connection, self.codex_home, installed_at), 0)

        with self.rollout.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(token_event(4, "2026-01-01T00:00:04Z", 240)) + "\n")
        self.assertEqual(read_status.sync_usage_history(connection, self.codex_home, installed_at), 0)

        summary = read_status.usage_history_summary(
            connection, installed_at, 1767225600, 1767225610
        )
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["input_tokens"], 100)
        self.assertEqual(summary["cached_input_tokens"], 40)
        self.assertEqual(summary["output_tokens"], 20)
        self.assertEqual(summary["total_tokens"], 120)
        connection.close()

    def test_incomplete_json_line_is_imported_after_newline_arrives(self):
        connection, _, installed_at, _ = read_status.open_history_database(
            self.codex_home, now=1767225601
        )
        encoded = json.dumps(token_event(3, "2026-01-01T00:00:03Z", 360))
        with self.rollout.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
        self.assertEqual(read_status.sync_usage_history(connection, self.codex_home, installed_at), 0)

        with self.rollout.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        self.assertEqual(read_status.sync_usage_history(connection, self.codex_home, installed_at), 1)
        connection.close()


if __name__ == "__main__":
    unittest.main()
