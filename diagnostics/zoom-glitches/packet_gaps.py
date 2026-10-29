#!/usr/bin/env python3
"""Report presentation timestamp gaps in one video stream."""
import argparse
import json
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("files", nargs="+")
parser.add_argument("--threshold", type=float, default=0.1)
args = parser.parse_args()
for filename in args.files:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_packets",
        "-show_entries", "packet=pts_time", "-of", "json", filename,
    ], check=True, capture_output=True, text=True)
    packets = json.loads(result.stdout)["packets"]
    times = [float(packet["pts_time"]) for packet in packets if "pts_time" in packet]
    pairs = list(zip(times, times[1:]))
    print(json.dumps({
        "file": filename,
        "packets_with_pts": len(times),
        "span_seconds": times[-1] - times[0] if times else None,
        "nonincreasing_pts": sum(b <= a for a, b in pairs),
        "gaps": [{"offset_seconds": a - times[0], "gap_seconds": b - a}
                 for a, b in pairs if b - a > args.threshold],
    }, indent=2))
