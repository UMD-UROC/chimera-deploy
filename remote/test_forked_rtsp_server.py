#!/usr/bin/env python3

import contextlib
import io
import unittest

import forked_rtsp_server as server


class FakeClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class FakeLoop:
    def __init__(self):
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1


class FakePad:
    def add_probe(self, probe_type, callback, name):
        self.probe_type = probe_type
        self.callback = callback
        self.name = name


class FakeProducer:
    def __init__(self, tee=object()):
        self.tee = tee

    def get_by_name(self, name):
        if name != "t" or self.tee is None:
            return None
        return self

    def get_static_pad(self, name):
        if name != "sink":
            return None
        return self.tee


class ProducerFrameWatchdogTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.loop = FakeLoop()
        self.watchdog = server.ProducerFrameWatchdog(self.loop, self.clock)
        self.pad = FakePad()
        self.watchdog.watch("rgb-fork", FakeProducer(self.pad))

    def test_recent_frame_keeps_watchdog_running(self):
        self.clock.now = server.PRODUCER_STALL_TIMEOUT_SECONDS - 1
        self.assertEqual(self.watchdog.check(), server.GLib.SOURCE_CONTINUE)
        self.assertEqual(self.loop.quit_calls, 0)
        self.assertIsNone(self.watchdog.failure)

    def test_buffer_resets_stall_deadline(self):
        self.clock.now = server.PRODUCER_STALL_TIMEOUT_SECONDS - 1
        self.assertEqual(
            self.pad.callback(None, None, self.pad.name),
            server.Gst.PadProbeReturn.OK,
        )
        self.clock.now += server.PRODUCER_STALL_TIMEOUT_SECONDS - 1
        self.assertEqual(self.watchdog.check(), server.GLib.SOURCE_CONTINUE)

    def test_stall_stops_loop_and_reports_failure(self):
        self.clock.now = server.PRODUCER_STALL_TIMEOUT_SECONDS
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = self.watchdog.check()
        self.assertEqual(result, server.GLib.SOURCE_REMOVE)
        self.assertEqual(self.loop.quit_calls, 1)
        self.assertEqual(
            self.watchdog.failure,
            "No frames from rgb-fork for 15 seconds; restarting rcam",
        )
        self.assertIn(self.watchdog.failure, output.getvalue())

    def test_missing_monitor_tee_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "has no tee"):
            self.watchdog.watch("invalid", FakeProducer(None))


if __name__ == "__main__":
    unittest.main()
