#!/usr/bin/env python3
"""Serves the ground relay's H.265 streams to ATAK as MPEG-TS with MISB ST 0601 KLV telemetry."""

import argparse
import sys
import time

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import GLib, Gst, GstRtspServer

import klv_config as conf
import klv_misb0601 as misb
import klv_projection as projection
from klv_telemetry import TelemetryListener

Gst.init(None)

KLV_APPSRC_NAME = "klv"
KLV_PERIOD_MS = int(1000.0 / conf.KLV_RATE_HZ)
STATUS_PERIOD_S = 1.0

MPEGTS_WITH_KLV_LAUNCH = """(
    rtspsrc location={source} protocols=udp latency=0 drop-on-latency=true !
    rtph265depay !
    h265parse config-interval=1 !
    video/x-h265,stream-format=byte-stream,alignment=au !
    mpegtsmux name=mux alignment=7 !
    rtpmp2tpay name=pay0 pt=33

    appsrc name={klv_appsrc} is-live=true format=time do-timestamp=true caps="meta/x-klv,parsed=true" !
    mux.
)"""


class KlvFeed:
    """Pushes one KLV packet per tick for as long as its RTSP media is alive."""

    def __init__(self, stream, appsrc):
        self._stream = stream
        self._appsrc = appsrc
        self._source_id = GLib.timeout_add(KLV_PERIOD_MS, self._push)

    def _push(self):
        packet = Gst.Buffer.new_wrapped(self._stream.packet())
        if self._appsrc.emit("push-buffer", packet) != Gst.FlowReturn.OK:
            self._source_id = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def stop(self, *_):
        if self._source_id is not None:
            GLib.source_remove(self._source_id)
            self._source_id = None


class AtakStream:
    """One configured stream: relay video in, telemetry from its aircraft, KLV-tagged MPEG-TS out."""

    def __init__(self, stream, source_host, source_port, verbose):
        self.mount = f"/{stream.atak_mount}"
        self.source = f"rtsp://{source_host}:{source_port}/{stream.source_mount}"
        self.platform_designation, _, self.image_source_sensor = stream.atak_mount.partition("/")
        self._camera = stream.camera
        self._telemetry = TelemetryListener.shared(stream.mavlink_endpoint)
        self._verbose = verbose
        self._last_status_time = 0.0

    def factory(self):
        factory = GstRtspServer.RTSPMediaFactory()
        factory.set_launch(MPEGTS_WITH_KLV_LAUNCH.format(source=self.source, klv_appsrc=KLV_APPSRC_NAME))
        factory.set_shared(True)
        factory.connect("media-configure", self._attach_klv_feed)
        return factory

    def _attach_klv_feed(self, _factory, media):
        feed = KlvFeed(self, media.get_element().get_by_name(KLV_APPSRC_NAME))
        media.connect("unprepared", feed.stop)

    def packet(self):
        identity = (
            (misb.UNIX_TIME_STAMP, time.time() * 1e6),
            (misb.UAS_LDS_VERSION_NUMBER, misb.UAS_LDS_VERSION),
            (misb.PLATFORM_DESIGNATION, self.platform_designation),
            (misb.IMAGE_SOURCE_SENSOR, self.image_source_sensor),
        )
        state = self._telemetry.state()
        if state is None:
            self._log_status("no telemetry")
            return misb.local_set(*identity)

        footprint = projection.project(
            state.position,
            state.height_above_ground_m,
            state.gimbal,
            self._camera.boresight_offset,
            self._camera.horizontal_fov_deg,
            self._camera.vertical_fov_deg,
        )
        self._log_status(f"{state.gimbal_source} {state.gimbal} -> {footprint.center if footprint else 'above horizon'}")

        return misb.local_set(*identity, *self._pose_items(state), *self._footprint_items(state, footprint))

    def _pose_items(self, state):
        return (
            (misb.SENSOR_LATITUDE, state.position.latitude_deg),
            (misb.SENSOR_LONGITUDE, state.position.longitude_deg),
            (misb.SENSOR_TRUE_ALTITUDE, state.altitude_amsl_m),
            (misb.PLATFORM_HEADING_ANGLE, state.attitude.yaw_deg),
            (misb.PLATFORM_PITCH_ANGLE, state.attitude.pitch_deg),
            (misb.PLATFORM_ROLL_ANGLE, state.attitude.roll_deg),
            (misb.SENSOR_HORIZONTAL_FIELD_OF_VIEW, self._camera.horizontal_fov_deg),
            (misb.SENSOR_VERTICAL_FIELD_OF_VIEW, self._camera.vertical_fov_deg),
            (misb.SENSOR_RELATIVE_AZIMUTH_ANGLE, (state.gimbal.yaw_deg - state.attitude.yaw_deg) % 360.0),
            (misb.SENSOR_RELATIVE_ELEVATION_ANGLE, state.gimbal.pitch_deg - state.attitude.pitch_deg),
            (misb.SENSOR_RELATIVE_ROLL_ANGLE, (state.gimbal.roll_deg - state.attitude.roll_deg) % 360.0),
        )

    def _footprint_items(self, state, footprint):
        if footprint is None:
            return ()
        ground_elevation_m = state.altitude_amsl_m - state.height_above_ground_m
        items = [
            (misb.SLANT_RANGE, footprint.slant_range_m),
            (misb.FRAME_CENTER_LATITUDE, footprint.center.latitude_deg),
            (misb.FRAME_CENTER_LONGITUDE, footprint.center.longitude_deg),
            (misb.FRAME_CENTER_ELEVATION, ground_elevation_m),
        ]
        for corner, latitude_field, longitude_field in zip(footprint.corners, misb.CORNER_LATITUDE_FIELDS, misb.CORNER_LONGITUDE_FIELDS):
            items.append((latitude_field, corner.latitude_deg))
            items.append((longitude_field, corner.longitude_deg))
        return tuple(items)

    def _log_status(self, message):
        now = time.monotonic()
        if self._verbose and now - self._last_status_time >= STATUS_PERIOD_S:
            self._last_status_time = now
            print(f"[KLV] {self.mount} {message}")


def main():
    parser = argparse.ArgumentParser(description="ATAK-facing RTSP server: ground relay H.265 muxed with MISB ST 0601 KLV")
    parser.add_argument("--source-host", default=conf.SOURCE_RTSP_HOST, help="host of the ground relay serving the video mounts")
    parser.add_argument("--source-port", type=int, default=conf.SOURCE_RTSP_PORT)
    parser.add_argument("--port", type=int, default=conf.ATAK_RTSP_PORT, help="port ATAK connects to")
    parser.add_argument("--advertise-ip", default=conf.GROUND_STATION_IP, help="IP printed in the ATAK stream URLs")
    parser.add_argument("--verbose", action="store_true", help="log telemetry and footprint once per second")
    args = parser.parse_args()

    server = GstRtspServer.RTSPServer()
    server.set_service(str(args.port))
    mounts = server.get_mount_points()

    streams = [AtakStream(stream, args.source_host, args.source_port, args.verbose) for stream in conf.STREAMS]
    for stream in streams:
        mounts.add_factory(stream.mount, stream.factory())

    if server.attach(None) == 0:
        print(f"[ERROR] Failed to attach RTSP server (couldn't bind port {args.port}).")
        sys.exit(1)

    print(f"[READY] Listening on rtsp://{args.advertise_ip}:{args.port}")
    print("ATAK streams (H.265 + KLV in MPEG-TS):")
    for stream in streams:
        print(f"  rtsp://{args.advertise_ip}:{args.port}{stream.mount} <- {stream.source}")

    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
