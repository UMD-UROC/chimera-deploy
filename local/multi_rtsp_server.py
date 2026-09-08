#!/usr/bin/env python3
import gi
import argparse
import sys
gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GLib

Gst.init(None)

SESSION_CLEANUP_INTERVAL_SECONDS = 5


def clean_expired_sessions(session_pool):
    removed_sessions = session_pool.cleanup()
    if removed_sessions:
        print(f"Removed {removed_sessions} expired RTSP session{'s' if removed_sessions != 1 else ''}.")
    return GLib.SOURCE_CONTINUE


def make_media_factory(pipeline):
    factory = GstRtspServer.RTSPMediaFactory()
    factory.set_launch(pipeline)
    factory.set_shared(False)
    factory.set_stop_on_disconnect(True)
    return factory


class MultiRTSPServer:
    def __init__(self, remote_ip, tags, pipes):
        self.server = GstRtspServer.RTSPServer()
        self.server.set_service("8554")
        GLib.timeout_add_seconds(
            SESSION_CLEANUP_INTERVAL_SECONDS,
            clean_expired_sessions,
            self.server.get_session_pool(),
        )
        mounts = self.server.get_mount_points()

        for tag, pipeline in zip(tags, pipes):
            mounts.add_factory(f"/{tag}", make_media_factory(pipeline))

        source_id = self.server.attach(None)
        if source_id == 0:
            print("[ERROR] Failed to attach RTSP server (couldn't bind socket).")
            sys.exit(1)

        # Now we know it's ready to accept connections; report the bound port
        bound_port = self.server.get_bound_port()
        print(f"[READY] Listening on rtsp://{remote_ip}:8554")
        print("RTSP streams:")
        for tag in tags:
            print(f"  rtsp://{remote_ip}:8554/{tag}")

def main():
    parser = argparse.ArgumentParser(description="Multi-stream GStreamer RTSP server")
    parser.add_argument('--remote-ip', help='IP address clients should use to connect (used for printing rtsp uris)', required=True)
    parser.add_argument('--tags', nargs='+', help='List of RTSP stream tags (used as mount points)', required=True)
    parser.add_argument('--pipes', nargs='+', help='List of GStreamer pipes (must match tags)', required=True)
    args = parser.parse_args()

    remote_ip = args.remote_ip
    tags = args.tags
    pipes = args.pipes

    # Validation: check count
    if len(tags) != len(pipes):
        print(f"[ERROR] Number of tags ({len(tags)}) does not match number of pipes ({len(pipes)}).")
        sys.exit(1)

    # Validation: check for duplicate tags
    duplicates = set(tag for tag in tags if tags.count(tag) > 1)
    if duplicates:
        for tag in duplicates:
            print(f"[ERROR] Duplicate tag detected: '{tag}'")
        sys.exit(1)

    # All good, start server
    server = MultiRTSPServer(remote_ip, tags, pipes)
    loop = GLib.MainLoop()
    loop.run()



if __name__ == "__main__":
    main()
