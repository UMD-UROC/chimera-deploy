#!/usr/bin/env python3
"""Compare daytime C1 PRO image controls and save the original controls."""
from video_pools import CONVERTER_BUFFERS

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time


DEVICE = '/dev/v4l/by-id/usb-Kurokesu_C1_PRO_HA4-L61MC-video-index2'
LOCK = '/tmp/c1-daytest.lock'
COARSE_VALUES = {
    'brightness': (-64, -32, -16, 0, 32, 64),
    'gamma': (72, 100, 200, 350, 500),
    'contrast': (0, 16, 32, 48, 64),
    'saturation': (0, 32, 64, 96, 128),
    'sharpness': (0, 2, 3, 4, 6),
    'hue': (-40, -20, 0, 20, 40),
    'backlight_compensation': (0, 1, 2),
    'power_line_frequency': (0, 1, 2),
}
TOUCHED = tuple(COARSE_VALUES)
AUTO = {'auto_exposure': 3, 'white_balance_automatic': 1}


def utc():
    return datetime.now(timezone.utc).isoformat()


def command(args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=5).stdout


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


class Controls:
    def __init__(self, device):
        self.device = device
        self.identity = command(['v4l2-ctl', '-d', device, '--info'])
        if 'C1 PRO' not in self.identity or 'uvcvideo' not in self.identity:
            raise RuntimeError('The selected device is not a C1 PRO UVC camera.')

    def read(self):
        raw = command(['v4l2-ctl', '-d', self.device, '--list-ctrls-menus'])
        values = {m[0]: int(m[1]) for m in re.findall(
            r'^\s*(\w+)\s+0x[0-9a-f]+.*?\bvalue=(-?\d+)', raw, re.M)}
        return values, raw

    def apply(self, values):
        if not values or set(values) - set(TOUCHED):
            raise RuntimeError('Only the supported image controls can change.')
        current, _ = self.read()
        changed = {key: value for key, value in values.items() if current.get(key) != value}
        if changed:
            command(['v4l2-ctl', '-d', self.device, '--set-ctrl',
                     ','.join(f'{key}={value}' for key, value in changed.items())])
        actual, _ = self.read()
        if any(actual.get(key) != value for key, value in values.items()):
            raise RuntimeError('The camera did not retain the requested controls.')


def check_auto(values):
    if any(values.get(key) != value for key, value in AUTO.items()):
        raise RuntimeError('Automatic exposure and automatic white balance must remain enabled.')


def service_pid():
    pid = int(command(['systemctl', 'show', 'rcam', '-p', 'MainPID', '--value']).strip())
    if pid <= 0:
        raise RuntimeError('The camera server is not active.')
    return pid


class Capture:
    """Read existing full-resolution NVMM output at five frames per second."""
    def __init__(self):
        import gi
        import numpy as np
        gi.require_version('Gst', '1.0')
        gi.require_version('GstVideo', '1.0')
        from gi.repository import Gst, GstVideo
        self.Gst, self.GstVideo, self.np = Gst, GstVideo, np
        Gst.init(None)
        self.pipeline = Gst.parse_launch(
            'nvunixfdsrc socket-path=/tmp/rgb_nv.sock do-timestamp=true ! '
            'video/x-raw(memory:NVMM),format=NV12,width=1920,height=1080 ! '
            'queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! '
            'videorate drop-only=true ! video/x-raw(memory:NVMM),framerate=5/1 ! '
            f'nvvidconv output-buffers={CONVERTER_BUFFERS} ! video/x-raw,format=BGRx ! '
            'appsink name=frames max-buffers=1 drop=true sync=false wait-on-eos=false')
        self.sink = self.pipeline.get_by_name('frames')
        self.last_pts = None
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.close()
            raise RuntimeError('The image reader could not start.')

    def frame(self, timeout=5):
        Gst = self.Gst
        message = self.pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if message:
            raise RuntimeError(str(message.parse_error()) if message.type == Gst.MessageType.ERROR
                               else 'The RGB stream ended.')
        sample = self.sink.emit('try-pull-sample', int(timeout * Gst.SECOND))
        if sample is None:
            raise RuntimeError('No RGB frame arrived before the timeout.')
        buffer = sample.get_buffer()
        if buffer.pts == Gst.CLOCK_TIME_NONE or (self.last_pts is not None and buffer.pts <= self.last_pts):
            raise RuntimeError('The RGB frame timestamp did not advance.')
        self.last_pts = buffer.pts
        info = self.GstVideo.VideoInfo.new_from_caps(sample.get_caps())
        ok, mapped = buffer.map(Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError('The RGB frame could not map to memory.')
        try:
            pixels = self.np.ndarray((info.height, info.width, 4), dtype=self.np.uint8,
                                     buffer=mapped.data, offset=info.offset[0],
                                     strides=(info.stride[0], 4, 1))
            return pixels[:, :, 2::-1].copy(), buffer.pts / Gst.SECOND
        finally:
            buffer.unmap(mapped)

    def close(self):
        self.pipeline.set_state(self.Gst.State.NULL)


def metrics(rgb):
    import numpy as np
    result = {}
    for name, region in [('full', rgb), ('upper', rgb[:rgb.shape[0] // 3]),
                         ('lower', rgb[rgb.shape[0] // 2:])]:
        y = region @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        result.update({
            f'{name}_mean_y': float(y.mean()),
            f'{name}_p99_y': float(np.percentile(y, 99)),
            f'{name}_channel_clip_pct': float((region >= 250).any(axis=2).mean() * 100),
            f'{name}_white_clip_pct': float((region >= 250).all(axis=2).mean() * 100),
            f'{name}_shadow_pct': float((y <= 16).mean() * 100),
        })
    small = rgb[::2, ::2] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lap = (small[:-2, 1:-1] + small[2:, 1:-1] + small[1:-1, :-2]
           + small[1:-1, 2:] - 4 * small[1:-1, 1:-1])
    result['laplacian_variance_halfres'] = float(lap.var())
    means = rgb.mean(axis=(0, 1))
    result['r_over_g'] = float(means[0] / max(means[1], 1))
    result['b_over_g'] = float(means[2] / max(means[1], 1))
    return result


def parameters(text):
    names = list(dict.fromkeys(name.strip() for name in text.split(',')))
    if not names or any(name not in COARSE_VALUES for name in names):
        raise argparse.ArgumentTypeError('Choose controls from: ' + ','.join(TOUCHED))
    return names


def profiles(original, selected=None):
    baseline = {key: original[key] for key in TOUCHED if key in original}
    sequence = [('baseline', 'baseline', baseline.copy())]
    for key in selected or TOUCHED:
        if key not in baseline:
            continue
        for value in COARSE_VALUES[key]:
            if value != original[key]:
                label = f'{key}_{value}'.replace('-', 'minus')
                sequence.append((key, label, {**baseline, key: value}))
    if len(sequence) == 1:
        raise RuntimeError('The camera exposes none of the selected image controls.')
    return baseline, sequence


def restore(output):
    path = output / 'state.json'
    if not path.exists():
        return
    state = json.loads(path.read_text())
    if state.get('restored'):
        return
    if state.get('status') in ('starting', 'running'):
        state.update(status='interrupted', ended_at=utc())
    if state.get('args', {}).get('mode') == 'observe':
        state.update(restored=True, restored_at=utc(), note='Observe mode wrote no camera controls.')
        atomic_json(path, state)
        return
    controls = Controls(state['device'])
    controls.apply(state['original_touched'])
    actual, raw = controls.read()
    state.update(restored=True, restored_at=utc(), final_controls=actual)
    atomic_json(path, state)
    (output / 'controls-restored.txt').write_text(raw)


def run(args, controls=None, capture_factory=Capture):
    from PIL import Image
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    controls = controls or Controls(args.device)
    original, raw = controls.read()
    check_auto(original)
    if shutil.disk_usage(output).free < 1024 ** 3:
        raise RuntimeError('At least 1 GiB of free storage is required.')
    baseline, sequence = profiles(original, args.parameters)
    if args.mode == 'observe':
        sequence = [('observe', 'observe', baseline)]
    pid = service_pid()
    state = dict(started_at=utc(), device=controls.device, original_controls=original,
                 original_touched=baseline, restored=False, rcam_pid=pid,
                 args=vars(args), profiles=sequence, planned_blocks=len(sequence),
                 skipped_parameters=[key for key in args.parameters if key not in baseline],
                 status='starting')
    state['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    atomic_json(output / 'state.json', state)
    (output / 'controls-before.txt').write_text(raw)
    (output / 'camera-info.txt').write_text(controls.identity)
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    reader = None
    started = time.monotonic()
    previous_cpu = time.process_time()
    previous_measurement = started
    try:
        reader = capture_factory()
        reader.frame(timeout=8)  # Check the image path before the first control write.
        state['status'] = 'running'
        atomic_json(output / 'state.json', state)
        with (output / 'samples.csv').open('w', newline='', buffering=1) as samples, \
                (output / 'events.jsonl').open('a', buffering=1) as events:
            writer = None
            for block, (parameter, label, values) in enumerate(sequence):
                if stopped:
                    break
                if service_pid() != pid:
                    raise RuntimeError('The camera server restarted. The comparison stopped.')
                current, _ = controls.read()
                check_auto(current)
                if args.mode != 'observe':
                    controls.apply(values)
                event = dict(utc=utc(), elapsed=time.monotonic() - started,
                             block=block, round=1, parameter=parameter,
                             profile=label, requested=values)
                events.write(json.dumps(event) + '\n')
                print(json.dumps(event), flush=True)
                settle_end = time.monotonic() + (args.settle if args.mode != 'observe' else 0)
                # Read continuously during settling so no old frame labels a new profile.
                while time.monotonic() < settle_end and not stopped:
                    reader.frame()
                end = time.monotonic() + args.seconds
                next_sample = next_image = time.monotonic()
                count = 0
                while time.monotonic() < end and not stopped:
                    rgb, pts = reader.frame()
                    now = time.monotonic()
                    if now < next_sample:
                        continue
                    if service_pid() != pid:
                        raise RuntimeError('The camera server restarted. The comparison stopped.')
                    current, _ = controls.read()
                    check_auto(current)
                    if any(current[key] != value for key, value in values.items()):
                        raise RuntimeError('Another process changed the test controls.')
                    row = dict(utc=utc(), elapsed=now - started, block=block, round=1,
                               parameter=parameter, requested_value=values.get(parameter, ''),
                               profile=label, source_pts=pts, brightness=current['brightness'],
                               backlight_compensation=current['backlight_compensation'],
                               auto_exposure=current['auto_exposure'],
                               white_balance_automatic=current['white_balance_automatic'],
                               white_balance_temperature=current.get('white_balance_temperature'),
                               exposure_time_absolute_readback=current.get('exposure_time_absolute'),
                               gain_readback=current.get('gain'), rcam_pid=pid,
                               controls_json=json.dumps(current, sort_keys=True),
                               frame_width=rgb.shape[1], frame_height=rgb.shape[0], image='')
                    cpu_now = time.process_time()
                    row.update(process_cpu_pct=100 * (cpu_now - previous_cpu) / max(now - previous_measurement, 0.001),
                               system_load1=os.getloadavg()[0],
                               process_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                    previous_cpu, previous_measurement = cpu_now, now
                    if now >= next_image:
                        name = f'{block:03d}_{label}_{count:04d}.jpg'
                        Image.fromarray(rgb).save(output / name, quality=95)
                        row['image'] = name
                        next_image = now + args.image_interval
                    row.update(metrics(rgb))
                    if writer is None:
                        writer = csv.DictWriter(samples, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    count += 1
                    next_sample = now + args.interval
                    if args.mode != 'observe':
                        break
                if not stopped and count == 0:
                    raise RuntimeError('The test block produced no measured frames.')
        state['status'] = 'stopped' if stopped else 'complete'
    except BaseException as error:
        state.update(status='failed', error=str(error))
        raise
    finally:
        state['ended_at'] = utc()
        atomic_json(output / 'state.json', state)
        try:
            if args.mode == 'observe':
                state.update(restored=True, restored_at=utc(), note='Observe mode wrote no camera controls.')
                atomic_json(output / 'state.json', state)
            else:
                restore(output)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if reader is not None:
                reader.close()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['run', 'observe', 'preflight', 'restore'])
    parser.add_argument('--device', default=DEVICE)
    parser.add_argument('--output', required=True)
    parser.add_argument('--parameters', type=parameters, default=list(TOUCHED))
    parser.add_argument('--seconds', type=float, default=0.4)
    parser.add_argument('--settle', type=float, default=0.4)
    parser.add_argument('--interval', type=float, default=0.4)
    parser.add_argument('--image-interval', type=float, default=0.4)
    args = parser.parse_args()
    for name in ('seconds', 'interval', 'image_interval'):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0.2:
            parser.error(f'{name} must be finite and at least 0.2 seconds.')
    if not math.isfinite(args.settle) or args.settle < 0.2:
        parser.error('Settle must be finite and at least 0.2 seconds.')
    with open(LOCK, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another C1 test holds the camera lock.')
        if args.mode == 'restore':
            restore(Path(args.output))
        elif args.mode == 'preflight':
            controls = Controls(args.device)
            values, _ = controls.read()
            check_auto(values)
            pid = service_pid()
            reader = Capture()
            try:
                frame, pts = reader.frame(timeout=8)
                next_frame, next_pts = reader.frame()
                if service_pid() != pid:
                    raise RuntimeError('The camera server restarted during preflight.')
                print(json.dumps(dict(utc=utc(), controls=values, rcam_pid=pid,
                                      shape=list(next_frame.shape), pts_step=next_pts - pts,
                                      metrics=metrics(frame)), indent=2))
            finally:
                reader.close()
        else:
            print(run(args))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'C1 test failed: {error}', file=sys.stderr)
        sys.exit(1)
