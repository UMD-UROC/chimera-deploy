#!/usr/bin/env python3

import os
import json
import time
import gi
import rtsp_config as conf

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GLib, GstRtspServer, GstVideo

Gst.init(None)

SEI_UUID = bytes.fromhex("00112233445566778899aabbccddeeff")
_frame_id = 0


def make_factory(launch):
    factory = GstRtspServer.RTSPMediaFactory()
    factory.set_shared(True)
    factory.set_launch(launch)
    factory.connect("media-configure", on_media_configure)
    return factory


def on_media_configure(factory, media):
    elem = media.get_element()
    for name, path in conf.SOCKETS.items():
        parse = elem.get_by_name(name)
        if parse:
            pad = parse.get_static_pad("src")
            if pad:
                pad.add_probe(Gst.PadProbeType.BUFFER, sei_probe_cb)


def sei_probe_cb(pad, info):
    global _frame_id
    buf = info.get_buffer()
    if not buf:
        return Gst.PadProbeReturn.OK

    payload = json.dumps({
        "ts_unix_ns": time.time_ns(),
        "frame_id": _frame_id,
    }, separators=(",", ":")).encode("utf-8")
    _frame_id += 1

    GstVideo.buffer_add_video_sei_user_data_unregistered_meta(
        buf, SEI_UUID, payload
    )
    return Gst.PadProbeReturn.OK


def cleanup_sockets():
    for name, path in conf.SOCKETS.items():
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def main():
    cleanup_sockets()
    producers = []

    for name, pipe in conf.PRODUCERS.items():
        print(f"{name} producer starting...")
        producer = Gst.parse_launch(pipe)
        producer.set_state(Gst.State.PLAYING)
        producers.append(producer)
        print(f"{name} producer started!")

    server = GstRtspServer.RTSPServer()
    server.set_service("8554")
    mounts = server.get_mount_points()

    for name, pipe in conf.FACTORIES.items():
        print(f"{name} factory starting...")
        factory = make_factory(pipe)
        mounts.add_factory(f"/{name}", factory)
        print(f"rtsp://127.0.0.1:8554/{name}")
        print(f"{name} factory started!")

    server.attach(None)

    loop = GLib.MainLoop()
    try:
        loop.run()
    finally:
        for producer in producers:
            producer.set_state(Gst.State.NULL)
        cleanup_sockets()


if __name__ == "__main__":
    main()