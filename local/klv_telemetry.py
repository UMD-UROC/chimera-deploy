#!/usr/bin/env python3
"""Latest MAVLink platform and gimbal state, one shared listener per endpoint."""

import math
import os
import threading
import time
from dataclasses import dataclass

os.environ["MAVLINK20"] = "1"  # the gimbal device messages only exist in MAVLink 2

from pymavlink import mavutil

import klv_config as conf
from klv_projection import Attitude, GeoPoint

YAW_IN_EARTH_FRAME = 64
HEADING_UNKNOWN = 65535

GIMBAL_MESSAGES_BY_PRIORITY = (
    "GIMBAL_DEVICE_ATTITUDE_STATUS",
    "GIMBAL_DEVICE_SET_ATTITUDE",
    "GIMBAL_MANAGER_SET_ATTITUDE",
)
TRACKED_MESSAGES = {"GLOBAL_POSITION_INT", "ATTITUDE", *GIMBAL_MESSAGES_BY_PRIORITY}
PLATFORM_ATTITUDE_FALLBACK = "PLATFORM_ATTITUDE"


@dataclass(frozen=True)
class PlatformState:
    position: GeoPoint
    altitude_amsl_m: float
    height_above_ground_m: float
    attitude: Attitude
    gimbal: Attitude
    gimbal_source: str


def _attitude_from_quaternion(quaternion):
    w, x, y, z = quaternion
    if any(math.isnan(component) for component in (w, x, y, z)):
        return None
    return Attitude(
        yaw_deg=math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))),
        pitch_deg=math.degrees(math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x))))),
        roll_deg=math.degrees(math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))),
    )


def _heading_deg(attitude, position):
    if attitude is not None:
        return math.degrees(attitude.yaw) % 360.0
    if position.hdg == HEADING_UNKNOWN:
        return 0.0
    return position.hdg / 100.0


class TelemetryListener:
    """Single reader per MAVLink endpoint; every stream on that aircraft shares one instance."""

    _by_endpoint = {}
    _by_endpoint_lock = threading.Lock()

    @classmethod
    def shared(cls, endpoint):
        with cls._by_endpoint_lock:
            listener = cls._by_endpoint.get(endpoint)
            if listener is None:
                listener = cls._by_endpoint[endpoint] = cls(endpoint)
                listener.start()
            return listener

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self._messages = {}
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._receive_forever, name=f"mavlink {self.endpoint}", daemon=True).start()

    def _receive_forever(self):
        while True:
            connection = None
            try:
                connection = mavutil.mavlink_connection(self.endpoint)
                print(f"[INFO] MAVLink listening on {self.endpoint}")
                while True:
                    message = connection.recv_match(type=TRACKED_MESSAGES, blocking=True, timeout=1.0)
                    if message is not None:
                        with self._lock:
                            self._messages[message.get_type()] = (time.monotonic(), message)
            except Exception as error:
                print(f"[WARN] MAVLink {self.endpoint} unavailable ({error}); retrying")
                time.sleep(conf.MAVLINK_RECONNECT_DELAY_S)
            finally:
                if connection is not None:
                    connection.close()

    def _fresh(self, message_type):
        with self._lock:
            entry = self._messages.get(message_type)
        if entry is None:
            return None
        received_at, message = entry
        return message if time.monotonic() - received_at <= conf.TELEMETRY_TIMEOUT_S else None

    def _gimbal(self, heading_deg):
        for message_type in GIMBAL_MESSAGES_BY_PRIORITY:
            message = self._fresh(message_type)
            if message is None:
                continue
            attitude = _attitude_from_quaternion(message.q)
            if attitude is None:
                continue
            yaw_deg = attitude.yaw_deg if message.flags & YAW_IN_EARTH_FRAME else attitude.yaw_deg + heading_deg
            return Attitude(yaw_deg % 360.0, attitude.pitch_deg, attitude.roll_deg), message_type

    def state(self):
        position = self._fresh("GLOBAL_POSITION_INT")
        if position is None:
            return None

        attitude = self._fresh("ATTITUDE")
        heading_deg = _heading_deg(attitude, position)
        platform = Attitude(
            yaw_deg=heading_deg,
            pitch_deg=math.degrees(attitude.pitch) if attitude is not None else 0.0,
            roll_deg=math.degrees(attitude.roll) if attitude is not None else 0.0,
        )
        gimbal, gimbal_source = self._gimbal(heading_deg) or (platform, PLATFORM_ATTITUDE_FALLBACK)

        return PlatformState(
            position=GeoPoint(position.lat / 1e7, position.lon / 1e7),
            altitude_amsl_m=position.alt / 1000.0,
            height_above_ground_m=max(position.relative_alt / 1000.0, 0.0),
            attitude=platform,
            gimbal=gimbal,
            gimbal_source=gimbal_source,
        )
