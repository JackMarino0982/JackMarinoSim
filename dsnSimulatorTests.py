"""Software-only regression checks; not physical ADC/OMS verification."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from dsnSimulatorCore import Simulator, RecordingReader, Sample, SCHEMA


class Clock:
    def __init__(self): self.now = 1_000_000_000
    def __call__(self): return self.now
    def advance(self, ms): self.now += int(ms * 1_000_000)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sim = Simulator(self.clock, capacity=2)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "recording.jsonl"

    def tearDown(self):
        self.sim.stop()
        self.tmp.cleanup()

    def record(self, codes=(0, 150, 255)):
        self.sim.set_mode("Simulator")
        self.sim.start()
        self.sim.begin_recording(self.path)
        expected = []
        for code in codes:
            self.clock.advance(50)
            self.sim.generate(code)
            expected.append(self.sim.publish())
        self.sim.stop()
        return expected

    def test_stale_uses_last_publication_not_generation(self):
        self.sim.start()
        self.sim.generate(42)
        self.clock.advance(80)
        self.sim.publish()
        self.sim.input_paused = True
        self.clock.advance(99)
        self.assertEqual(self.sim.status, "VALID (SIMULATOR ONLY)")
        self.clock.advance(1)
        self.assertEqual(self.sim.status, "STALE (SIMULATOR)")
        self.sim.generate(8)
        self.assertFalse(self.sim.queue)
        self.sim.input_paused = False
        self.sim.generate(8)
        self.sim.publish()
        self.assertEqual(self.sim.status, "VALID (SIMULATOR ONLY)")

    def test_bounded_queue_reports_loss_and_gap(self):
        self.sim.start()
        self.sim.begin_recording(self.path)
        for code in (10, 20, 30): self.sim.generate(code)
        self.assertEqual(len(self.sim.queue), 2)
        self.assertEqual(self.sim.loss, 1)
        self.assertEqual(self.sim.publish().code, 20)
        self.sim.end_recording()
        with self.path.open() as f:
            rows = [json.loads(line) for line in f]
        self.assertEqual(rows[1], {"kind": "gap", "lost": 1, "reason": "demo_buffer_drop_oldest"})
        self.assertEqual(rows[2]["sequence"], 2)

    def test_record_and_replay_exact_metadata(self):
        expected = self.record()
        live_time = self.sim.last_live_publication
        self.sim.open_recording(self.path)
        self.sim.play()
        observed = [self.sim.replay_next() for _ in expected]
        self.assertEqual(observed, expected)
        self.assertEqual(self.sim.last_live_publication, live_time)
        self.assertEqual(self.sim.status, "REPLAY")
        self.sim.replay_next()
        self.assertFalse(self.sim.running)
        self.assertIsNone(self.sim.reader)

    def test_replay_pause_and_restart(self):
        expected = self.record()
        self.sim.open_recording(self.path)
        self.sim.play()
        self.assertEqual(self.sim.replay_next(), expected[0])
        self.sim.pause_replay()
        self.assertIsNone(self.sim.replay_next())
        self.assertEqual(self.sim.status, "REPLAY PAUSED")
        self.sim.play()
        self.assertEqual(self.sim.replay_next(), expected[1])
        self.sim.stop()
        self.sim.play()
        self.assertEqual(self.sim.replay_next(), expected[0])

    def test_hardware_and_settings_denied_at_core_boundary(self):
        with self.assertRaises(ValueError): self.sim.set_mode("Live Hardware")
        for identity in (None, "operator", "admin"):
            with self.assertRaises(PermissionError):
                self.sim.request_acquisition_setting("sample_rate", 100, identity)
        self.assertEqual(self.sim.mode, "Simulator")

    def test_mode_switch_requires_stop(self):
        self.sim.start()
        with self.assertRaises(ValueError): self.sim.set_mode("Replay")
        self.sim.stop()
        self.sim.set_mode("Replay")
        with self.assertRaises(ValueError): self.sim.start()

    def test_recording_does_not_overwrite(self):
        self.path.write_text("keep me", encoding="utf-8")
        self.sim.start()
        with self.assertRaises(FileExistsError): self.sim.begin_recording(self.path)
        self.assertEqual(self.path.read_text(), "keep me")

    def test_new_start_has_new_epoch_and_sequence(self):
        self.sim.start(); self.sim.generate(1); first = self.sim.publish()
        self.sim.stop(); self.sim.start(); self.sim.generate(2); second = self.sim.publish()
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertEqual(second.sequence, 1)

    def test_recording_write_failure_visible_and_acquisition_continues(self):
        class Broken(io.StringIO):
            def write(self, text): raise OSError("test disk failure")
        self.sim.start(); self.sim.writer = Broken()
        self.sim.generate(20); self.sim.publish()
        self.assertIsNone(self.sim.writer)
        self.assertIn("Recording failed", self.sim.error)
        self.assertTrue(self.sim.running)

    def test_invalid_header_rejected(self):
        self.path.write_text('{"kind":"session","schema":"other"}\n')
        with self.assertRaises(ValueError): self.sim.open_recording(self.path)
        self.assertEqual(self.sim.mode, "Simulator")

    def test_partial_and_corrupt_records_stop_replay_visibly(self):
        for tail in ('{"kind":', '{"kind":"sample","code":true}\n', '\n'):
            if self.path.exists(): self.path.unlink()
            self.record((12,))
            with self.path.open("a") as f: f.write(tail)
            self.sim.open_recording(self.path); self.sim.play()
            self.sim.replay_next(); self.sim.replay_next()
            self.assertIn("Replay stopped", self.sim.error)
            self.assertFalse(self.sim.running)
            self.assertIsNone(self.sim.reader)

    def test_duplicate_sequence_rejected(self):
        self.record((4,))
        lines = self.path.read_text().splitlines()
        with self.path.open("a") as f: f.write(lines[1] + "\n")
        self.sim.open_recording(self.path); self.sim.play()
        self.sim.replay_next(); self.sim.replay_next()
        self.assertIn("duplicate", self.sim.error)

    def test_null_and_duplicate_json_fields_are_not_silent_eof(self):
        for tail in ('null\n', '{"kind":"gap","kind":"sample"}\n'):
            if self.path.exists(): self.path.unlink()
            self.record((12,))
            with self.path.open("a") as f: f.write(tail)
            self.sim.open_recording(self.path); self.sim.play()
            self.sim.replay_next(); self.sim.replay_next()
            self.assertIn("Replay stopped", self.sim.error)

    def test_boolean_code_and_oversized_record_rejected(self):
        for tail in ('{"kind":"sample","code":true}\n', '{"text":"' + 'x'*1_048_576 + '"}\n'):
            if self.path.exists(): self.path.unlink()
            self.record((12,))
            with self.path.open("a") as f: f.write(tail)
            self.sim.open_recording(self.path); self.sim.play()
            self.sim.replay_next(); self.sim.replay_next()
            self.assertIn("Replay stopped", self.sim.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
