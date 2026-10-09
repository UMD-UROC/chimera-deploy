#!/usr/bin/env python3
"""Verify mode isolation without opening camera devices."""
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


class CameraSelectionTest(unittest.TestCase):
    def config(self, camera="rgb", model="chimera_v3", base="0",
               profile="aircraft", missing=False, override=""):
        with tempfile.TemporaryDirectory() as home:
            stack = Path(home) / "px4-sim-stack"
            stack.mkdir()
            (stack / ".env").write_text(
                f'UAS_FLEET="{model}"\nUAS_BASE={base}\n'
                f'COMPOSE_PROFILES={profile}\nONBOARD_CAMERA={camera}\n')
            with patch("pathlib.Path.home", return_value=Path(home)), \
                    patch("v4l2_devices.find_device",
                          return_value=None if missing else "/dev/video-test"), \
                    patch.dict(os.environ, {"RCAM_CAMERAS": override}):
                return runpy.run_path(str(Path(__file__).with_name("rtsp_config.py")))

    def test_v3_night_has_no_rgb_producer_or_mounts(self):
        config = self.config("thermal", override="pilot,rgb,thermal")
        self.assertEqual(set(config["PRODUCERS"]), {"pilot-fork", "thermal-fork"})
        self.assertEqual(set(config["FACTORIES"]), {"pilot", "pilotl", "thermal", "thermall"})

    def test_v3_day_has_no_thermal_producer_or_mounts(self):
        config = self.config()
        self.assertEqual(set(config["PRODUCERS"]), {"pilot-fork", "rgb-fork"})
        self.assertEqual(set(config["FACTORIES"]), {"pilot", "pilotl", "rgb", "rgbl"})

    def test_v2_both_modes_keep_existing_cameras(self):
        for camera in ("rgb", "thermal"):
            with self.subTest(camera=camera):
                config = self.config(camera, model="chimera_v2")
                self.assertIsNone(config["SELECTED_CAMERAS"])
                self.assertEqual(len(config["PRODUCERS"]), 3)

    def test_ground_and_simulator_are_unchanged(self):
        for options in ({"profile": "ground"}, {"base": "10"}):
            with self.subTest(options=options):
                self.assertIsNone(self.config("thermal", **options)["SELECTED_CAMERAS"])

    def test_absent_selected_camera_does_not_enable_other_usb_camera(self):
        config = self.config("thermal", missing=True)
        self.assertEqual(set(config["PRODUCERS"]), {"pilot-fork"})
        self.assertEqual(set(config["FACTORIES"]), {"pilot", "pilotl"})

    def test_invalid_v3_mode_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid ONBOARD_CAMERA"):
            self.config("invalid")


if __name__ == "__main__":
    unittest.main()
