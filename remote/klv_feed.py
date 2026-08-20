#!/usr/bin/env python3
"""Frame-accurate KLV: ask for a geolocation when a frame is encoded, emit it when the frame is released."""

import socket
import struct
import threading
import time
from collections import OrderedDict

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

import klv_misb0601 as misb

REQUEST_FORMAT = ">QQ"
REPLY_HEADER_FORMAT = ">Q"
REPLY_HEADER_SIZE = struct.calcsize(REPLY_HEADER_FORMAT)
MAX_REPLY_SIZE = 4096
PENDING_FRAME_LIMIT = 240
REPLY_POLL_TIMEOUT_S = 0.5


def _running_time(pad, buffer):
    """The muxer aggregates in running time; an RTSP media's segment is offset from raw PTS."""
    segment_event = pad.get_sticky_event(Gst.EventType.SEGMENT, 0)
    if segment_event is None:
        return buffer.pts
    return segment_event.parse_segment().to_running_time(Gst.Format.TIME, buffer.pts)


def _telemetry_free_packet():
    return misb.local_set(
        (misb.UNIX_TIME_STAMP, time.time() * 1e6),
        (misb.UAS_LDS_VERSION_NUMBER, misb.UAS_LDS_VERSION),
    )


class KlvFeed:
    """Binds one RTSP media's delayed video branch to the geolocation node.

    The delay queue is the seam: a frame entering it is what we request a geolocation for,
    and a frame leaving it is what we emit that geolocation alongside, carrying its PTS.
    """

    def __init__(self, appsrc, delay_queue, geolocation_address, frame_interval=1):
        self._appsrc = appsrc
        self._delay_queue = delay_queue
        self._geolocation_address = tuple(geolocation_address)
        self._frame_interval = max(1, frame_interval)
        self._encoded_frames = 0
        self._released_frames = 0
        self._packets_by_pts = OrderedDict()
        self._lock = threading.Lock()
        self._stopping = threading.Event()

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.settimeout(REPLY_POLL_TIMEOUT_S)
        self._reader = threading.Thread(target=self._receive_replies, name="klv replies", daemon=True)
        self._reader.start()

        self._request_probe = self._add_probe("sink", self._on_frame_encoded)
        self._release_probe = self._add_probe("src", self._on_frame_released)

    def _add_probe(self, pad_name, handler):
        pad = self._delay_queue.get_static_pad(pad_name)
        return pad, pad.add_probe(Gst.PadProbeType.BUFFER, handler)

    def _capture_unix_us(self, pad, buffer):
        clock = self._delay_queue.get_clock()
        if clock is None:
            return time.time() * 1e6
        age_ns = clock.get_time() - (self._delay_queue.get_base_time() + _running_time(pad, buffer))
        return (time.time_ns() - age_ns) / 1000.0

    def _on_frame_encoded(self, pad, info):
        self._encoded_frames += 1
        if self._encoded_frames % self._frame_interval:
            return Gst.PadProbeReturn.OK
        buffer = info.get_buffer()
        request = struct.pack(REQUEST_FORMAT, buffer.pts, int(self._capture_unix_us(pad, buffer)))
        try:
            self._socket.sendto(request, self._geolocation_address)
        except OSError:
            pass
        return Gst.PadProbeReturn.OK

    def _on_frame_released(self, pad, info):
        self._released_frames += 1
        if self._released_frames % self._frame_interval:
            return Gst.PadProbeReturn.OK
        buffer = info.get_buffer()
        release_time = _running_time(pad, buffer)
        packet = Gst.Buffer.new_wrapped(self._take_packet(buffer.pts))
        packet.pts = release_time
        packet.dts = release_time
        packet.duration = buffer.duration
        self._appsrc.emit("push-buffer", packet)
        return Gst.PadProbeReturn.OK

    def _take_packet(self, pts):
        with self._lock:
            packet = self._packets_by_pts.pop(pts, None)
        return packet if packet is not None else _telemetry_free_packet()

    def _receive_replies(self):
        while not self._stopping.is_set():
            try:
                reply = self._socket.recv(MAX_REPLY_SIZE)
            except socket.timeout:
                continue
            except OSError:
                return
            if len(reply) <= REPLY_HEADER_SIZE:
                continue
            pts, = struct.unpack_from(REPLY_HEADER_FORMAT, reply)
            with self._lock:
                self._packets_by_pts[pts] = reply[REPLY_HEADER_SIZE:]
                while len(self._packets_by_pts) > PENDING_FRAME_LIMIT:
                    self._packets_by_pts.popitem(last=False)

    def stop(self, *_):
        if self._stopping.is_set():
            return
        self._stopping.set()
        for pad, probe_id in (self._request_probe, self._release_probe):
            pad.remove_probe(probe_id)
        self._socket.close()
