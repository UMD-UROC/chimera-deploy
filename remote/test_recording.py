"""Recorder failures must leave the other bag and video processes alive."""

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
PX4SIM_ROOT = Path(os.environ.get("PX4SIM_ROOT", ROOT.parent / "px4-sim-stack"))


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("recorder did not reach the expected state")


def alive(pid):
    stat = Path(f"/proc/{pid}/stat")
    return stat.exists() and not stat.read_text().split(") ", 1)[1].startswith("Z ")


@pytest.fixture
def recording(tmp_path):
    checkout = tmp_path / "chimera-deploy"
    for name in ("record_processes.sh", "record_all_common.sh", "remote_record_all.sh",
                 "record_nv_streams.sh", "record_rtsp_streams.sh", "video_pools.py"):
        target = checkout / "remote" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "remote" / name, target)
    (checkout / "local").mkdir()
    shutil.copy2(ROOT / "local/local_record_all.sh", checkout / "local")
    setup = tmp_path / "setup.bash"
    setup.touch()
    common = checkout / "remote/record_all_common.sh"
    common.write_text(common.read_text().replace("/opt/ros/humble/setup.bash", str(setup)))
    workspace = tmp_path / "workspace"
    (workspace / "install").mkdir(parents=True)
    (workspace / "install/setup.bash").touch()
    safe = checkout / "remote/safe_rosbag_record.sh"
    safe.write_text('#!/bin/bash\nexec ros2 bag record "$@"\n')
    safe.chmod(0o755)

    # Test the actual shell scripts without ROS, cameras, or an RTSP server.
    binary = tmp_path / "bin"
    binary.mkdir()
    stub = binary / "ros2"
    stub.write_text('''#!/usr/bin/env python3
import json, os, pathlib, signal, sys, time
root = pathlib.Path(os.environ['RECORD_TEST_ROOT'])
args = sys.argv[1:]
if pathlib.Path(sys.argv[0]).name == 'ros2':
    name = 'bag'
    if not (root / 'bag.startup-fail').exists():
        pathlib.Path(args[args.index('-o') + 1]).mkdir()
else:
    source = next(a for a in args if a.startswith(('location=rtsp:', 'socket-path=')))
    name = source.rsplit('/', 1)[-1].replace('_nv.sock', '')
(root / (name + '.args')).write_text(json.dumps(args))
(root / (name + '.pid')).write_text(str(os.getpid()))
stopping = False
def stop(sig, frame):
    global stopping
    stopping = True
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
while not stopping:
    if (root / (name + '.fail')).exists() or (root / (name + '.startup-fail')).exists():
        (root / (name + '.failed')).touch()
        sys.exit(23)
    time.sleep(.02)
(root / (name + '.stopped')).touch()
''')
    stub.chmod(0o755)
    shutil.copy2(stub, binary / "gst-launch-1.0")
    docker = binary / "docker"
    docker.write_text('''#!/usr/bin/env python3
import os, pathlib, time
root = pathlib.Path(os.environ['RECORD_TEST_ROOT'])
while not (root / 'container-stopped').exists():
    time.sleep(.02)
''')
    docker.chmod(0o755)

    # The NVMM script checks for local Unix sockets before it starts GStreamer.
    sockets = []
    nv = checkout / "remote/record_nv_streams.sh"
    source = nv.read_text()
    for name in ("pilot", "rgb", "thermal"):
        path = tmp_path / f"{name}_nv.sock"
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(path))
        sockets.append(sock)
        source = source.replace(f"/tmp/{name}_nv.sock", str(path))
    nv.write_text(source)

    processes = []

    def start(world, streams="pilotl1 rgbl1 thermall1", video=True, supervised=False):
        script = "local/local_record_all.sh" if world == "ground" else "remote/remote_record_all.sh"
        env = dict(os.environ, CHIMERA_VIDEO_POOL_POLICY=str(__import__("video_pools").POLICY_PATH), HOME=str(tmp_path), PATH=f"{binary}:{os.environ['PATH']}",
                   BAG_ROOT=str(workspace), BAG_NAME="session", RECORD_STREAMS=streams,
                   RECORD_VIDEO=str(int(video)), RECORD_TEST_ROOT=str(tmp_path),
                   PX4SIM_RECORD_STOP_GRACE="2")
        command = [str(checkout / script)]
        if supervised:
            command = [sys.executable, str(PX4SIM_ROOT / "scripts/record-session.py"),
                       "original-container-id", *command]
        with (tmp_path / "record.log").open("w") as log:
            process = subprocess.Popen(command, env=env,
                                       stdout=log, stderr=log, start_new_session=True)
        processes.append(process)
        return process

    yield start, tmp_path

    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            pytest.fail("recorders did not stop after the session received SIGTERM")
    for sock in sockets:
        sock.close()


@pytest.mark.parametrize("world", ["ground", "aircraft"])
@pytest.mark.parametrize("failure", ["bag-startup", "bag", "video", "all-video"])
def test_failed_recorder_does_not_stop_siblings(recording, world, failure):
    start, directory = recording
    videos = ("pilotl1", "rgbl1", "thermall1") if world == "ground" else ("pilot", "rgb", "thermal")
    failed = {"bag"} if failure.startswith("bag") else set(videos if failure == "all-video" else videos[:1])
    if failure == "bag-startup":
        (directory / "bag.startup-fail").touch()
    process = start(world)
    names = ("bag", *videos)
    wait_for(lambda: all((directory / f"{name}.pid").exists() for name in names))
    for name in failed:
        (directory / f"{name}.fail").touch()
    wait_for(lambda: all((directory / f"{name}.failed").exists() for name in failed))
    wait_for(lambda: all(not alive(int((directory / f"{name}.pid").read_text())) for name in failed))
    # Give a parent that incorrectly uses wait -n time to terminate siblings.
    time.sleep(0.15)
    assert process.poll() is None, (directory / "record.log").read_text()
    for name in set(names) - failed:
        assert alive(int((directory / f"{name}.pid").read_text()))

    if world == "ground":
        for name in videos:
            args = json.loads((directory / f"{name}.args").read_text())
            assert f"location=rtsp://127.0.0.1:8554/{name}" in args
            assert any(arg.endswith("_session.ts") for arg in args)

    os.killpg(process.pid, signal.SIGINT)
    process.wait(timeout=5)
    for name in set(names) - failed:
        wait_for(lambda: (directory / f"{name}.stopped").exists())
        wait_for(lambda: not alive(int((directory / f"{name}.pid").read_text())))


def test_missing_stream_does_not_delay_other_recorders(recording):
    start, directory = recording
    (directory / "missing.startup-fail").touch()
    process = start("ground", streams="missing rgbl3")
    wait_for(lambda: (directory / "missing.failed").exists())
    wait_for(lambda: (directory / "rgbl3.pid").exists())
    assert process.poll() is None
    assert alive(int((directory / "bag.pid").read_text()))
    assert alive(int((directory / "rgbl3.pid").read_text()))


def test_bags_only_finishes_when_bag_exits(recording):
    start, directory = recording
    process = start("ground", video=False)
    wait_for(lambda: (directory / "bag.pid").exists())
    (directory / "bag.fail").touch()
    assert process.wait(timeout=5) == 23
    assert sorted(path.stem for path in directory.glob("*.pid")) == ["bag"]


@pytest.mark.parametrize("missing", [("pilot",), ("pilot", "rgb", "thermal")])
def test_absent_nv_sockets_leave_bag_and_other_cameras_alive(recording, missing):
    start, directory = recording
    for name in missing:
        (directory / f"{name}_nv.sock").unlink()
    process = start("aircraft")
    remaining = {"bag", "pilot", "rgb", "thermal"} - set(missing)
    wait_for(lambda: all((directory / f"{name}.pid").exists() for name in remaining))
    wait_for(lambda: all(f"Skipping {name}" in (directory / "record.log").read_text() for name in missing))
    time.sleep(0.15)
    assert process.poll() is None
    for name in remaining:
        assert alive(int((directory / f"{name}.pid").read_text()))
    for name in missing:
        assert not (directory / f"{name}.pid").exists()


@pytest.mark.skipif(not (PX4SIM_ROOT / "px4sim").exists(), reason="requires the px4-sim-stack checkout")
@pytest.mark.parametrize("world", ["ground", "aircraft"])
@pytest.mark.parametrize("failure", [None, "bag", "video", "missing"])
@pytest.mark.parametrize("trigger", ["record-stop", "container-stopped"])
def test_session_stop_reaches_every_remaining_recorder(recording, world, failure, trigger):
    start, directory = recording
    videos = ["pilotl1", "rgbl1", "thermall1"] if world == "ground" else ["pilot", "rgb", "thermal"]
    if failure == "missing":
        if world == "ground":
            (directory / f"{videos[0]}.startup-fail").touch()
        else:
            (directory / f"{videos[0]}_nv.sock").unlink()
            videos.pop(0)
    process = start(world, supervised=True)
    names = ["bag", *videos]
    wait_for(lambda: all((directory / f"{name}.pid").exists() for name in names))
    if failure in ("bag", "video"):
        name = "bag" if failure == "bag" else videos[0]
        (directory / f"{name}.fail").touch()
        wait_for(lambda: (directory / f"{name}.failed").exists())
    assert process.poll() is None

    if trigger == "container-stopped":
        (directory / trigger).touch()
        assert process.wait(timeout=15) == 0
    else:
        # Run the same stop function that `px4sim record stop` calls.
        source = (PX4SIM_ROOT / "px4sim").read_text()
        functions = []
        for name in ("recording_status", "stop_native_recording"):
            offset = source.index(f"{name}() {{")
            functions.append(source[offset:source.index("\n}", offset) + 2])
        (directory / "record.pid").write_text(f"{process.pid}\n")
        script = '''
set -euo pipefail
RECORD_PID_FILE=$1/record.pid
RECORD_MODE_FILE=$1/record.mode
RECORD_BAG_FILE=$1/record.bag
RECORD_SIM_FILE=$1/record.sim
say() { :; }
'''
        script += "\n".join(functions) + "\nstop_native_recording\n"
        with subprocess.Popen(["bash", "-c", script, "_", str(directory)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as stopper:
            # Reap the supervisor so recording_status can observe its exit.
            assert process.wait(timeout=15) == 0
            _, error = stopper.communicate(timeout=20)
            assert stopper.returncode == 0, error
        assert not (directory / "record.pid").exists()

    for name in names:
        assert not alive(int((directory / f"{name}.pid").read_text()))
        assert (directory / f"{name}.failed").exists() or (directory / f"{name}.stopped").exists()
