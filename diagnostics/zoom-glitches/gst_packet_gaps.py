#!/usr/bin/env python3
"""Measure H.265 access-unit timing without decoding pixels."""
import json
import sys
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst

Gst.init(None)
pipeline = Gst.parse_launch(
    'filesrc name=input ! tsdemux ! h265parse name=parser ! '
    'video/x-h265,alignment=au ! fakesink sync=false')
pipeline.get_by_name('input').set_property('location', sys.argv[1])
pts = []


def note(_pad, info):
    value = info.get_buffer().pts
    if value != Gst.CLOCK_TIME_NONE:
        pts.append(value / Gst.SECOND)
    return Gst.PadProbeReturn.OK


pipeline.get_by_name('parser').get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER, note)
pipeline.set_state(Gst.State.PLAYING)
try:
    message = pipeline.get_bus().timed_pop_filtered(
        60 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
    if message is None:
        raise RuntimeError('Video parsing exceeded 60 seconds')
    if message.type == Gst.MessageType.ERROR:
        raise RuntimeError(str(message.parse_error()))
finally:
    pipeline.set_state(Gst.State.NULL)
pairs = list(zip(pts, pts[1:]))
print(json.dumps(dict(file=sys.argv[1], access_units_with_pts=len(pts),
    span_seconds=pts[-1] - pts[0] if pts else None,
    max_gap_seconds=max((b-a for a,b in pairs), default=None),
    nonincreasing_pts=sum(b <= a for a,b in pairs),
    gaps_over_half_second=[dict(offset_seconds=a-pts[0], gap_seconds=b-a)
                          for a,b in pairs if b-a > 0.5]), indent=2))
