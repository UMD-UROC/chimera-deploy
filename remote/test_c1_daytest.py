"""Test control restoration and image measurements without a camera."""
import argparse
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import c1_daytest as suite


class FakeControls:
    device = '/dev/fake-c1'
    identity = 'C1 PRO test device'

    def __init__(self):
        self.values = dict(brightness=0, backlight_compensation=1,
                           auto_exposure=3, white_balance_automatic=1)
        self.calls = []

    def read(self):
        return self.values.copy(), 'test controls'

    def apply(self, values):
        self.calls.append(values.copy())
        self.values.update(values)


class FakeCapture:
    def __init__(self):
        self.count = 0

    def frame(self, timeout=5):
        self.count += 1
        return np.full((12, 16, 3), 100, dtype=np.uint8), self.count

    def close(self):
        pass


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 0.1
        return self.value


class DayTest(unittest.TestCase):
    def args(self, output, mode='run'):
        return argparse.Namespace(mode=mode, output=str(output), device=FakeControls.device,
                                  rounds=1, seconds=1, settle=0.1, interval=0.1,
                                  image_interval=0.5)

    def execute(self, args, controls, factory=FakeCapture, pid=None):
        with patch.object(suite, 'Controls', return_value=controls), \
                patch.object(suite, 'service_pid', side_effect=pid or (lambda: 123)), \
                patch.object(suite.time, 'monotonic', side_effect=Clock()):
            return suite.run(args, controls, factory)

    def test_suite_restores_original_controls_and_keeps_automatic_modes(self):
        controls = FakeControls()
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'run'
            self.execute(self.args(output), controls)
            state = json.loads((output / 'state.json').read_text())
            self.assertTrue(state['restored'])
            self.assertEqual(state['status'], 'complete')
            self.assertEqual(controls.values['brightness'], 0)
            self.assertEqual(controls.values['backlight_compensation'], 1)
            self.assertTrue(all(set(call) == set(suite.TOUCHED) for call in controls.calls))
            with (output / 'samples.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len({r['block'] for r in rows}), 7)
            self.assertTrue(all(r['auto_exposure'] == '3' for r in rows))

    def test_capture_failure_after_candidate_write_restores_controls(self):
        controls = FakeControls()

        class FailedCapture(FakeCapture):
            def frame(self, timeout=5):
                if controls.values['backlight_compensation'] == 0:
                    raise RuntimeError('The stream stalled.')
                return super().frame(timeout)

        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'run'
            with self.assertRaisesRegex(RuntimeError, 'stalled'):
                self.execute(self.args(output), controls, FailedCapture)
            self.assertEqual(controls.values['backlight_compensation'], 1)
            self.assertTrue(json.loads((output / 'state.json').read_text())['restored'])

    def test_observe_mode_never_writes_controls(self):
        controls = FakeControls()
        with tempfile.TemporaryDirectory() as root:
            self.execute(self.args(Path(root) / 'observe', 'observe'), controls)
        self.assertEqual(controls.calls, [])

    def test_server_restart_aborts_and_restores(self):
        controls = FakeControls()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, 'restarted'):
                self.execute(self.args(Path(root) / 'run'), controls, pid=iter([123, 456]).__next__)
        self.assertEqual(controls.values['backlight_compensation'], 1)

    def test_manual_exposure_is_rejected_before_a_write(self):
        controls = FakeControls()
        controls.values['auto_exposure'] = 1
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, 'Automatic exposure'):
                self.execute(self.args(Path(root) / 'run'), controls)
        self.assertEqual(controls.calls, [])

    def test_clipping_is_separate_from_mean_brightness(self):
        rgb = np.array([[[255, 255, 255], [255, 0, 0]],
                        [[0, 0, 0], [100, 100, 100]],
                        [[100, 100, 100], [100, 100, 100]]], dtype=np.uint8)
        # Use a larger image for the sharpness region.
        result = suite.metrics(np.repeat(np.repeat(rgb, 3, axis=0), 3, axis=1))
        self.assertAlmostEqual(result['full_channel_clip_pct'], 100 / 3)
        self.assertAlmostEqual(result['full_white_clip_pct'], 100 / 6)
        self.assertAlmostEqual(result['full_shadow_pct'], 100 / 6)

    def test_recovery_restores_snapshot_after_process_loss(self):
        controls = FakeControls()
        controls.values.update(brightness=-8, backlight_compensation=0)
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            suite.atomic_json(output / 'state.json', dict(
                device=controls.device, original_touched=dict(brightness=0, backlight_compensation=1),
                restored=False))
            with patch.object(suite, 'Controls', return_value=controls):
                suite.restore(output)
                suite.restore(output)
        self.assertEqual(len(controls.calls), 1)
        self.assertEqual(controls.values['brightness'], 0)

    def test_partial_control_failure_restores_original_values(self):
        class PartialControls(FakeControls):
            def apply(self, values):
                super().apply(values)
                if values['brightness'] == -4:
                    raise RuntimeError('A control write failed after a partial update.')

        controls = PartialControls()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, 'partial update'):
                self.execute(self.args(Path(root) / 'run'), controls)
        self.assertEqual(controls.values['brightness'], 0)
        self.assertEqual(controls.values['backlight_compensation'], 1)

    def test_observe_recovery_does_not_write_controls(self):
        controls = FakeControls()
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            suite.atomic_json(output / 'state.json', dict(
                device=controls.device, original_touched=dict(brightness=0, backlight_compensation=1),
                args=dict(mode='observe'), restored=False))
            with patch.object(suite, 'Controls', return_value=controls):
                suite.restore(output)
        self.assertEqual(controls.calls, [])


if __name__ == '__main__':
    unittest.main()
