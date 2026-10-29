#!/usr/bin/env python3
"""Build the private Humble transport library without changing system ROS."""

import fcntl
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET


def prepare(build=True):
    source = Path(__file__).resolve().parent / "vendor/rosbag2_transport"
    installed = Path("/opt/ros/humble/share/rosbag2_transport/package.xml")
    version = ET.parse(installed).findtext("version")
    if version not in {"0.15.16", "0.15.17"}:
        raise RuntimeError(f"Unsupported rosbag2_transport version {version}. Review its ABI before recording.")
    digest = hashlib.sha256((version + platform.machine()).encode())
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.suffix != ".md":
            digest.update(str(path.relative_to(source)).encode())
            digest.update(path.read_bytes())
    root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "chimera/rosbag2" / digest.hexdigest()[:20]
    root.mkdir(parents=True, exist_ok=True)
    library = root / "librosbag2_transport.so"
    with (root / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (root / "complete").exists():
            if not build:
                raise RuntimeError("Native recording is not prepared. Restart through px4sim first.")
            with (root / "build.log").open("w") as log:
                commands = [
                    ["/usr/bin/cmake", "-S", str(source), "-B", str(root),
                     "-DBUILD_TESTING=OFF", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
                     "-DCMAKE_CXX_STANDARD=17", "-DPYTHON_EXECUTABLE=/usr/bin/python3"],
                    ["/usr/bin/cmake", "--build", str(root), "--target", "rosbag2_transport", "--parallel", "2"],
                ]
                for command in commands:
                    result = subprocess.run(command, stdout=log, stderr=log)
                    if result.returncode:
                        raise RuntimeError(f"Transport build failed. Read {root / 'build.log'}")
            if not library.is_file():
                raise RuntimeError(f"Transport build did not produce {library}")
            (root / "complete").touch()
    return library.parent


if __name__ == "__main__":
    print(prepare(build="--cached" not in sys.argv))
