import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("stream_speed", Path(__file__).resolve().parents[1] / "stream_speed.py")
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SpeedMeterTests(unittest.TestCase):
    def setUp(self):
        self.meter = module.SpeedMeter(list)
        self.meter.apply({"type": "snapshot", "revision": 10, "conversationState": {
            "items": [{"type": "agentMessage", "text": "old"},
                      {"type": "commandExecution", "text": "tool"}]}}, 0)
        self.rev = 10

    def patch(self, value, now, index=0):
        self.meter.apply({"type": "patches", "baseRevision": self.rev,
                          "revision": self.rev + 1, "patches": [
                              {"op": "replace", "path": ["items", index, "text"], "value": value}]}, now)
        self.rev += 1

    def test_history_duplicates_and_tools_are_not_output(self):
        self.assertEqual(self.meter.metric(1)["status"], "idle")
        self.patch("old", 1)
        self.patch("tool output", 1, 1)
        self.assertEqual(self.meter.metric(2)["status"], "idle")

    def test_stream_window_and_idle(self):
        self.patch("oldabcd", 1)
        self.assertEqual(self.meter.metric(1)["status"], "warming")
        self.assertEqual(self.meter.metric(2)["tokens_per_second"], 4)
        self.patch("oldabcdefgh", 3)
        self.assertEqual(self.meter.metric(3)["tokens_per_second"], 4)
        self.assertEqual(self.meter.metric(7)["status"], "idle")
        self.assertEqual(self.meter.metric(7)["tokens_per_second"], 4)

    def test_tool_pause_holds_speed_until_output_resumes(self):
        self.patch("oldabcd", 1)
        self.assertEqual(self.meter.metric(2)["tokens_per_second"], 4)
        self.patch("tool output", 2.1, 1)
        self.assertEqual(self.meter.metric(3)["tokens_per_second"], 4)
        self.assertEqual(self.meter.metric(10)["tokens_per_second"], 4)
        self.patch("oldabcdefghij", 11)
        self.assertEqual(self.meter.metric(11)["tokens_per_second"], 4)
        self.patch("oldabcdefghijkl", 12)
        self.assertEqual(self.meter.metric(12)["tokens_per_second"], 8)

    def test_snapshot_resets_and_revision_gap_is_rejected(self):
        self.patch("oldabcd", 1)
        self.meter.apply({"type": "snapshot", "revision": 20, "conversationState": {}}, 2)
        self.assertEqual(self.meter.metric(3)["status"], "idle")
        with self.assertRaises(ValueError):
            self.meter.apply({"type": "patches", "baseRevision": 19, "revision": 21}, 4)

    def test_replacement_is_not_generated_output(self):
        self.patch("replacement", 1)
        self.assertEqual(self.meter.metric(2)["status"], "idle")

    def test_completion_preserves_unsampled_text(self):
        self.patch("oldabcd", 1)
        self.meter.apply({"type": "patches", "baseRevision": self.rev,
                          "revision": self.rev + 1, "patches": [
                              {"op": "replace", "path": ["items", 0],
                               "value": {"type": "agentMessage", "text": "oldabcd"}}]}, 1.1)
        self.assertEqual(self.meter.metric(2)["tokens_per_second"], 4)


if __name__ == "__main__":
    unittest.main()
