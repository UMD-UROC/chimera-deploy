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


def make_factory(name, launch):
    try:
        Gst.parse_launch(launch)
    except GLib.Error as error:
        raise RuntimeError(f"{name} factory pipeline is invalid: {error}") from error

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


def retire_producer(name, producer, mounts, retired):
    """Take a dead camera off the air, the way a missing one never goes on it.

    A producer fails when its camera has gone, and leaving it up costs far more
    than the stream it can no longer carry. Its socket files stay on disk, so a
    client still mounts the path and asks for media. That media is built on the
    same main loop every other camera is served from, and it waits there on a
    socket nobody writes to, holding the healthy streams up behind it. One dead
    sensor takes the whole server down with it, which is how a thermal camera
    dropping off the USB bus blinded the visible light picture as well.

    Unmounting answers that client instead of parking it, and the cameras that
    are still attached go on serving. This is what rtsp_config does at startup
    for a camera that never appeared, done at the moment one leaves.
    """
    if name in retired:
        return
    retired.add(name)
    producer.set_state(Gst.State.NULL)

    group = conf.CAMERA_GROUPS.get(name)
    if group is None:
        print(f"{name} producer retired, but it owns no streams this file knows")
        return

    for factory in group["factories"]:
        mounts.remove_factory(f"/{factory}")
        print(f"{name} producer gone: unmounted /{factory}")
    for socket in group["sockets"]:
        try:
            os.unlink(conf.SOCKETS[socket])
        except FileNotFoundError:
            pass
    print(f"{name} producer retired: {group['card']} is off the air and the "
          f"other cameras are untouched. It comes back with rcam, because the "
          f"device is resolved once at startup.")


def on_producer_message(_bus, message, data):
    name, producer, mounts, retired = data
    if message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"{name} producer ERROR: {err}")
        print(f"{name} producer DEBUG: {debug}")
        retire_producer(name, producer, mounts, retired)
    elif message.type == Gst.MessageType.WARNING:
        warn, debug = message.parse_warning()
        print(f"{name} producer WARNING: {warn}")
        print(f"{name} producer DEBUG: {debug}")
    elif message.type == Gst.MessageType.EOS:
        # A camera is a live source. It does not reach the end of anything, so
        # an EOS here means the device stopped being there.
        print(f"{name} producer EOS")
        retire_producer(name, producer, mounts, retired)


def watch_producer(name, producer, mounts, retired):
    bus = producer.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_producer_message, (name, producer, mounts, retired))


def main():
    cleanup_sockets()

    for card, reason in conf.PRUNED_CAMERAS:
        print(f"[WARN] {card} is not being served: {reason}.")

    # The server first, because a producer that dies has to be able to take its
    # own mounts down with it, and it can only do that against mounts that
    # already exist.
    server = GstRtspServer.RTSPServer()
    server.set_service("8554")
    mounts = server.get_mount_points()
    retired = set()

    for name, pipe in conf.FACTORIES.items():
        print(f"{name} factory starting...")
        factory = make_factory(name, pipe)
        mounts.add_factory(f"/{name}", factory)
        print(f"rtsp://127.0.0.1:8554/{name}")
        print(f"{name} factory started!")

    producers = []
    for name, pipe in conf.PRODUCERS.items():
        print(f"{name} producer starting...")
        producer = Gst.parse_launch(pipe)
        watch_producer(name, producer, mounts, retired)
        result = producer.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError(f"{name} producer failed to start")
        producers.append((name, producer))
        print(f"{name} producer started!")

    server.attach(None)

    loop = GLib.MainLoop()
    try:
        loop.run()
    finally:
        for name, producer in producers:
            print(f"{name} producer stopping...")
            producer.set_state(Gst.State.NULL)
        cleanup_sockets()


if __name__ == "__main__":
    main()
