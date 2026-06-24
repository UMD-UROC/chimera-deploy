#!/usr/bin/env python3

import os
import gi
import rtsp_config as conf
from typing import Dict, Any

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import Gst, GLib, GstRtspServer

Gst.init(None)


def make_factory(launch):
    factory = GstRtspServer.RTSPMediaFactory()
    factory.set_shared(True)
    factory.set_launch(launch)
    return factory


def cleanup_sockets():
    for name, path in conf.SOCKETS.items():
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def main():
    cleanup_sockets()

    for name, pipe in conf.PRODUCERS.items():
        print(f"{name} producer starting...")
        producer = Gst.parse_launch(pipe)
        producer.set_state(Gst.State.PLAYING)
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
        producer.set_state(Gst.State.NULL)
        cleanup_sockets()


if __name__ == "__main__":
    main()