"""The relay must parse and share one upstream connection per stream."""

from pathlib import Path
import unittest
import importlib.util

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
from multi_rtsp_server import make_media_factory


class RelayTest(unittest.TestCase):
    def test_configured_relay_parses_without_opening_cameras(self):
        text = Path(__file__).with_name("local_start_camera_server.sh").read_text()
        common = next(line for line in text.splitlines() if line.startswith('common="'))[8:-1]
        description = "( rtspsrc location=rtsp://127.0.0.1:8555/pilotl " + common
        pipeline = Gst.parse_launch(description)
        pipeline.set_state(Gst.State.NULL)
        factory = make_media_factory(description)
        self.assertTrue(factory.is_shared())
        self.assertFalse(factory.get_property("stop-on-disconnect"))

    def test_recording_starts_with_a_complete_keyframe(self):
        source = Path(__file__).resolve().parents[1] / "remote/run_gst_recording.py"
        spec = importlib.util.spec_from_file_location("gst_recording", source)
        recorder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recorder)
        pipeline = Gst.parse_launch("appsrc name=input is-live=true format=time ! identity name=parser ! fakesink name=out signal-handoffs=true sync=false")
        received = []
        pipeline.get_by_name("out").connect("handoff", lambda _s, b, _p: received.append(b.extract_dup(0, b.get_size())))
        pipeline.get_by_name("parser").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, recorder.first_keyframe)
        try:
            pipeline.set_state(Gst.State.PLAYING)
            appsrc = pipeline.get_by_name("input")
            for payload, flags in [(b"partial", Gst.BufferFlags.DELTA_UNIT),
                                   (b"bad", Gst.BufferFlags.CORRUPTED),
                                   (b"keyframe", Gst.BufferFlags(0)),
                                   (b"next", Gst.BufferFlags.DELTA_UNIT)]:
                buffer = Gst.Buffer.new_wrapped(payload)
                buffer.set_flags(flags)
                appsrc.emit("push-buffer", buffer)
            appsrc.emit("end-of-stream")
            message = pipeline.get_bus().timed_pop_filtered(2 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            self.assertIsNotNone(message)
            self.assertEqual(message.type, Gst.MessageType.EOS)
            self.assertEqual(received, [b"keyframe", b"next"])
        finally:
            pipeline.set_state(Gst.State.NULL)
