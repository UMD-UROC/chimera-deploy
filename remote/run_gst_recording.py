#!/usr/bin/env python3
"""Record complete H.265 pictures and finalize the muxer on shutdown."""

import signal
import sys
import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst


def first_keyframe(_pad, info):
    buffer = info.get_buffer()
    if buffer.get_flags() & (Gst.BufferFlags.DELTA_UNIT | Gst.BufferFlags.CORRUPTED):
        return Gst.PadProbeReturn.DROP
    return Gst.PadProbeReturn.REMOVE


def main(args):
    Gst.init(None)
    pipeline = Gst.parse_launchv(args)
    parser = pipeline.get_by_name("record_parser")
    parser.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, first_keyframe)
    loop = GLib.MainLoop()
    result = 0
    stopping = False

    def stop(_sig, _frame):
        nonlocal stopping
        if not stopping:
            stopping = True
            pipeline.send_event(Gst.Event.new_eos())
            GLib.timeout_add_seconds(3, lambda: (loop.quit(), False)[1])

    def message(_bus, msg):
        nonlocal result
        if msg.type == Gst.MessageType.ERROR:
            error, debug = msg.parse_error()
            print(f"ERROR: {error}: {debug}", file=sys.stderr, flush=True)
            result = 1
            loop.quit()
        elif msg.type == Gst.MessageType.WARNING:
            warning, debug = msg.parse_warning()
            print(f"WARNING: {warning}: {debug}", file=sys.stderr, flush=True)
        elif msg.type == Gst.MessageType.EOS:
            loop.quit()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", message)
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            return 1
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        bus.remove_signal_watch()
    return result


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
