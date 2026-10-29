"""The relay must parse and share one upstream connection per stream."""

from pathlib import Path
import unittest

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
