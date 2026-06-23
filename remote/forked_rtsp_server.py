#!/usr/bin/env python3

import os
import gi
import rtsp_config as conf
from typing import Dict, Any

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import Gst, GLib, GstRtspServer

Gst.init(None)


def set_property_if_present(element, name, value):
    if element is not None and element.find_property(name):
        element.set_property(name, value)
        return True
    return False


def find_rtpbin(media_element):
    if media_element is None:
        return None

    for name in ("rtpbin0", "rtpbin"):
        rtpbin = media_element.get_by_name(name)
        if rtpbin is not None:
            return rtpbin

    iterator = media_element.iterate_recurse()
    while True:
        result, child = iterator.next()
        if result == Gst.IteratorResult.OK:
            factory = child.get_factory()
            if factory is not None and factory.get_name() == "rtpbin":
                return child
        elif result == Gst.IteratorResult.RESYNC:
            iterator.resync()
        else:
            return None


def configure_media(_factory, media):
    media_element = media.get_element()
    rtpbin = find_rtpbin(media_element)
    if rtpbin is None:
        print("RTSP media configured without visible rtpbin; NTP timing was not adjusted.")
        return

    set_property_if_present(rtpbin, "ntp-sync", True)
    set_property_if_present(rtpbin, "ntp-time-source", 0)
    set_property_if_present(rtpbin, "rtcp-sync-send-time", False)
    set_property_if_present(rtpbin, "rtcp-sync-interval", 0)
    print("RTSP rtpbin configured for NTP/RTCP timing.")


def make_factory(launch):
    factory = GstRtspServer.RTSPMediaFactory()
    factory.set_shared(True)
    factory.set_launch(launch)
    factory.connect("media-configure", configure_media)

    if hasattr(factory, "set_clock"):
        factory.set_clock(Gst.SystemClock.obtain())

    if hasattr(factory, "set_publish_clock_mode"):
        mode = getattr(
            GstRtspServer.RTSPPublishClockMode,
            "CLOCK_AND_OFFSET",
            getattr(GstRtspServer.RTSPPublishClockMode, "CLOCK", None),
        )
        if mode is not None:
            factory.set_publish_clock_mode(mode)

    if hasattr(factory, "set_latency"):
        factory.set_latency(0)

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
