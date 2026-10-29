#!/usr/bin/env python3
"""Verify mode isolation without opening camera devices."""
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


class CameraSelectionTest(unittest.TestCase):
    def config(self, camera="rgb", model="v3", base="0",
               profile="aircraft", missing=False, override="",
               fleet="chimera_v3 chimera_v3 chimera_v2 chimera_v2",
               derived=True, number="1", declared=True):
        with tempfile.TemporaryDirectory() as home:
            stack = Path(home) / "px4-sim-stack"
            stack.mkdir()
            host = Path(home) / 'host.env'
            host.write_text(f'UAS_NUM={number}\n' +
                            (f'CHIMERA_MODEL={model}\n' if declared else ''))
            model_line = f'UAS_MODEL={model}\n' if derived else ''
            (stack / ".env").write_text(
                f'UAS_FLEET="{fleet}"\n{model_line}UAS_BASE={base}\n'
                f'COMPOSE_PROFILES={profile}\nONBOARD_CAMERA={camera}\n')
            with patch("aircraft_config.HOST_ENV", host), \
                    patch("pathlib.Path.home", return_value=Path(home)), \
                    patch("v4l2_devices.find_device",
                          return_value=None if missing else "/dev/video-test"), \
                    patch.dict(os.environ, {"RCAM_CAMERAS": override}):
                return runpy.run_path(str(Path(__file__).with_name("rtsp_config.py")))

    def test_rgb_modes_keep_decoder_headroom_and_codec_options(self):
        for mode, parser in (("h264", "h264parse"), ("mjpeg", "jpegparse")):
            with self.subTest(mode=mode), patch.dict(os.environ, {"RGB_SOURCE": mode}):
                pipeline = self.config()["PRODUCERS"]["rgb-fork"]
                self.assertEqual(pipeline.count("nvv4l2decoder"), 1)
                self.assertIn("num-extra-surfaces=55", pipeline)
                self.assertIn("enable-max-performance=1", pipeline)
                self.assertIn(parser, pipeline)
                self.assertEqual("mjpeg=1" in pipeline, mode == "mjpeg")
                if mode == "h264":
                    self.assertIn("stream-format=byte-stream,alignment=au", pipeline)

    def test_v3_night_has_no_rgb_producer_or_mounts(self):
        config = self.config("thermal", override="pilot,rgb,thermal")
        self.assertEqual(set(config["PRODUCERS"]), {"pilot-fork", "thermal-fork"})
        self.assertEqual(set(config["FACTORIES"]), {"pilot", "pilotl", "thermal", "thermall"})

    def test_v3_day_has_no_thermal_producer_or_mounts(self):
        config = self.config()
        self.assertEqual(set(config["PRODUCERS"]), {"pilot-fork", "rgb-fork"})
        self.assertEqual(set(config["FACTORIES"]), {"pilot", "pilotl", "rgb", "rgbl"})

    def test_single_vehicle_fleet_keeps_v3_isolation(self):
        config = self.config("thermal", fleet="chimera_v3")
        self.assertEqual(set(config["PRODUCERS"]), {"pilot-fork", "thermal-fork"})

    def test_empty_camera_selection_defaults_to_day(self):
        config = self.config("")
        self.assertEqual(set(config["PRODUCERS"]), {"pilot-fork", "rgb-fork"})

    def test_v2_both_modes_keep_existing_cameras(self):
        for camera in ("rgb", "thermal"):
            with self.subTest(camera=camera):
                config = self.config(camera, model="v2")
                self.assertIsNone(config["SELECTED_CAMERAS"])
                self.assertEqual(len(config["PRODUCERS"]), 3)

    def test_aircraft_rejects_ground_or_simulator_env(self):
        for options in ({"profile": "ground"}, {"base": "10"}):
            with self.subTest(options=options):
                with self.assertRaisesRegex(RuntimeError, "Aircraft .env requires"):
                    self.config("thermal", **options)

    def test_absent_selected_camera_does_not_enable_other_usb_camera(self):
        config = self.config("thermal", missing=True)
        self.assertEqual(set(config["PRODUCERS"]), {"pilot-fork"})
        self.assertEqual(set(config["FACTORIES"]), {"pilot", "pilotl"})

    def test_legacy_aircraft_with_missing_derived_model_still_isolates(self):
        for number in ('1', '2'):
            with self.subTest(number=number):
                config = self.config('thermal', derived=False, declared=False, number=number)
                self.assertNotIn('rgb-fork', config['PRODUCERS'])
                self.assertNotIn('rgbl', config['FACTORIES'])

    def test_invalid_v3_mode_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid ONBOARD_CAMERA"):
            self.config("invalid")


if __name__ == "__main__":
    unittest.main()
