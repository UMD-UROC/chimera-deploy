#!/usr/bin/env python3
"""Restart one video recorder after an error or a sustained output stall."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def stop_process(process):
    for sig, grace in ((signal.SIGINT, 5), (signal.SIGTERM, 2), (signal.SIGKILL, 1)):
        if process.poll() is not None:
            return
        process.send_signal(sig)
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            continue


def record(output, command):
    output = Path(output)
    status_path = output.with_suffix(".status.json")
    stopping = False

    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    attempt = 0
    state = {}

    def status(**fields):
        state.update(fields, updated=time.time())
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state) + "\n")
        temporary.replace(status_path)

    stall = float(os.environ.get("RECORD_VIDEO_STALL_SECONDS", "15"))
    with output.with_suffix(".log").open("a", buffering=1) as log:
        while not stopping:
            attempt += 1
            segment = output if attempt == 1 else output.with_name(f"{output.stem}-part{attempt:03d}.ts")
            args = [f"location={segment}" if arg == f"location={output}" else arg for arg in command]
            status(state="connecting", attempt=attempt, path=str(segment), bytes=0, error="")
            log.write(f"{time.time():.3f} START {args!r}\n")
            process = subprocess.Popen(args, stdout=log, stderr=log)
            size = 0
            last_growth = time.monotonic()
            try:
                while not stopping and process.poll() is None:
                    current = segment.stat().st_size if segment.exists() else 0
                    if current > size:
                        last_growth = time.monotonic()
                    size = current
                    status(state="recording" if size and time.monotonic() - last_growth < 3 else "waiting",
                           bytes=size)
                    if time.monotonic() - last_growth > stall:
                        status(state="retrying", error=f"No output growth for {stall:g} seconds")
                        break
                    time.sleep(.25)
            finally:
                stop_process(process)
            size = segment.stat().st_size if segment.exists() else 0
            if not size:
                segment.unlink(missing_ok=True)
            log.write(f"{time.time():.3f} STOP exit={process.returncode} bytes={size}\n")
            status(state="stopped" if stopping else "retrying", bytes=size,
                   error=state.get("error") or (f"Recorder exited with status {process.returncode}" if not stopping else ""))
            deadline = time.monotonic() + 3
            while not stopping and time.monotonic() < deadline:
                time.sleep(.1)
    return 0


if __name__ == "__main__":
    sys.exit(record(sys.argv[1], sys.argv[3:]))
