"""Exercise video recovery and file cleanup with a real child process."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


WORKER = Path(__file__).with_name("record_video_worker.py")


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError("Video worker did not reach the expected state")


def test_stalled_video_restarts_without_overwriting_saved_segment(tmp_path):
    output = tmp_path / "video-test.ts"
    child = tmp_path / "source.py"
    child.write_text('''import pathlib, sys, time
p = pathlib.Path(sys.argv[1].split('=', 1)[1])
p.write_bytes(b'x' * 1880)
time.sleep(60)
''')
    process = subprocess.Popen([sys.executable, str(WORKER), str(output), "--",
                                sys.executable, str(child), f"location={output}"],
                               env=dict(os.environ, RECORD_VIDEO_STALL_SECONDS=".6"))
    try:
        second = tmp_path / "video-test-part002.ts"
        wait_for(lambda: second.exists())
        assert output.read_bytes() == second.read_bytes() == b"x" * 1880
    finally:
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=10) == 0
    state = json.loads(output.with_suffix(".status.json").read_text())
    assert state["attempt"] >= 2
    assert state["state"] == "stopped"


def test_failed_empty_video_leaves_log_and_status(tmp_path):
    output = tmp_path / "video-test.ts"
    process = subprocess.Popen([sys.executable, str(WORKER), str(output), "--",
                                sys.executable, "-c", "import sys; print('source unavailable'); sys.exit(1)"])
    state_path = output.with_suffix(".status.json")
    try:
        def retrying():
            return state_path.exists() and json.loads(state_path.read_text())["state"] == "retrying"
        wait_for(retrying)
        assert "status 1" in json.loads(state_path.read_text())["error"]
        assert not output.exists()
        assert "source unavailable" in output.with_suffix(".log").read_text()
    finally:
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=10) == 0
