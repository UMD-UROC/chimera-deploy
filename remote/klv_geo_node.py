#!/usr/bin/env python3
"""Answers rcam's per-frame requests with a MISB ST 0601 packet localized by tf_loc."""

import math
import os
import socket
import struct
import threading
import time

import rclpy
from collections import Counter

from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from builtin_interfaces.msg import Time as TimeMsg
from cdcl_umd_msgs.msg import TargetBox, TargetBoxArray
from cdcl_umd_msgs.srv import TBALocalization
from geometry_msgs.msg import TransformStamped
from sensor_msgs.msg import CameraInfo
from vision_msgs.msg import BoundingBox2D, Point2D, Pose2D

from umd_uas.tf_loc import quat_2_euler, tf_2_compass_heading

import klv_misb0601 as misb
import rtsp_config as conf

REQUEST_FORMAT = ">QQ"
REQUEST_SIZE = struct.calcsize(REQUEST_FORMAT)
REPLY_HEADER_FORMAT = ">Q"
# tf_loc registers this relative to its namespace, not under its node name
LOCALIZATION_SERVICE = "tba_loczn"
REPORT_PERIOD_S = 5.0

FRAME_CENTRE_INDEX = 0
CORNER_INDICES = (1, 2, 3, 4)


def sample_pixels(width, height):
    """Frame centre first, then the corners in ST 0601 order: upper left, upper right, lower right, lower left."""
    width, height = float(width), float(height)
    return (
        (width / 2.0, height / 2.0),
        (0.0, 0.0),
        (width, 0.0),
        (width, height),
        (0.0, height),
    )


def _degenerate_box(index, pixel):
    return TargetBox(
        data_source_id=index,
        target_bbox=BoundingBox2D(center=Pose2D(position=Point2D(x=pixel[0], y=pixel[1])), size_x=1.0, size_y=1.0),
    )


def _unix_us_to_stamp(unix_us):
    return TimeMsg(sec=int(unix_us // 1_000_000), nanosec=int(unix_us % 1_000_000) * 1000)


def _failure_kind(message):
    if "Cache does not contain" in message:
        return "gps gap"
    if "points backwards" in message:
        return "ray misses ground"
    return "localization failed"


def _located(fix):
    return fix is not None and not (fix.latitude == 0.0 and fix.longitude == 0.0)


def _best_fix(box):
    """tf_loc leaves the rangefinder-backed gimbal plane zeroed when it cannot establish one."""
    return box.target_location_gimbal_plane if _located(box.target_location_gimbal_plane) else box.target_location_altimeter_plane


def _compass_heading(quaternion):
    transform = TransformStamped()
    transform.transform.rotation = quaternion
    return tf_2_compass_heading(transform)


def _aerospace_angles(quaternion):
    """tf_loc works in ENU/FLU; ST 0601 wants nose-up pitch and compass yaw."""
    roll_deg, pitch_deg, _ = quat_2_euler(quaternion.x, quaternion.y, quaternion.z, quaternion.w)
    return -pitch_deg, roll_deg


def field_of_view_deg(camera_info):
    horizontal = 2.0 * math.atan(camera_info.width / (2.0 * camera_info.k[0]))
    vertical = 2.0 * math.atan(camera_info.height / (2.0 * camera_info.k[4]))
    return math.degrees(horizontal), math.degrees(vertical)


class GeolocationResponder(Node):
    """One UDP request per frame in, one ST 0601 packet out, localized at that frame's capture time."""

    def __init__(self):
        super().__init__("klv_geo")
        self.declare_parameter("uas_number", os.environ.get("UAS_NUM", "3"))
        self.declare_parameter("image_source_sensor", "rgb")
        self.declare_parameter("stream_width", conf.RGB_LOWRES_WIDTH)
        self.declare_parameter("stream_height", conf.RGB_LOWRES_HEIGHT)

        uas_number = self.get_parameter("uas_number").get_parameter_value().string_value
        self.platform_designation = f"uas{uas_number}"
        self.image_source_sensor = self.get_parameter("image_source_sensor").get_parameter_value().string_value
        self.stream_width = self.get_parameter("stream_width").get_parameter_value().integer_value
        self.stream_height = self.get_parameter("stream_height").get_parameter_value().integer_value
        self.sample_pixels = sample_pixels(self.stream_width, self.stream_height)

        transient_local = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
        self._camera_info = None
        self.create_subscription(CameraInfo, f"/{self.platform_designation}/camera/camera_info", self._on_camera_info, transient_local)
        self._localization = self.create_client(
            TBALocalization,
            f"/{self.platform_designation}/{LOCALIZATION_SERVICE}",
            callback_group=ReentrantCallbackGroup(),
        )

        self._last_report = 0.0
        self._outcomes = Counter()
        self._round_trips_ms = []
        self._last_detail = ""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(conf.KLV_GEOLOCATION_ADDRESSES[conf.RGB_LOWRES_KLV])
        threading.Thread(target=self._serve_requests, name="klv requests", daemon=True).start()
        self.get_logger().info(
            f"answering {self.platform_designation} {self.image_source_sensor} KLV requests on "
            f"{conf.KLV_GEOLOCATION_ADDRESSES[conf.RGB_LOWRES_KLV]}"
        )

    def _record(self, outcome, detail=""):
        """Counts are the useful signal here: how often a frame is actually localized."""
        self._outcomes[outcome] += 1
        if detail:
            self._last_detail = detail
        now = time.monotonic()
        if now - self._last_report < REPORT_PERIOD_S:
            return
        self._last_report = now
        summary = ", ".join(f"{count} {name}" for name, count in self._outcomes.most_common())
        if self._round_trips_ms:
            ordered = sorted(self._round_trips_ms)
            summary += (f" | round trip median {ordered[len(ordered) // 2]:.0f} ms,"
                        f" max {ordered[-1]:.0f} ms (budget {conf.KLV_ROUNDTRIP_NS / 1e6:.0f} ms)")
            self._round_trips_ms.clear()
        failed = any(name != "localized" for name in self._outcomes)
        self._outcomes.clear()
        report = self.get_logger().warn if failed else self.get_logger().info
        report(f"last {REPORT_PERIOD_S:.0f}s: {summary}" + (f" | {self._last_detail}" if failed else ""))

    def _on_camera_info(self, camera_info):
        self._camera_info = camera_info

    def _serve_requests(self):
        while rclpy.ok():
            request, requester = self._socket.recvfrom(REQUEST_SIZE)
            if len(request) != REQUEST_SIZE:
                continue
            frame_pts, capture_unix_us = struct.unpack(REQUEST_FORMAT, request)
            if self._camera_info is None:
                self._record("no camera_info")
                continue
            if not self._localization.service_is_ready():
                self._record("no localization server", self._localization.srv_name)
                continue
            asked_at = time.monotonic()
            future = self._localization.call_async(self._localization_request(capture_unix_us))
            future.add_done_callback(
                lambda done, pts=frame_pts, us=capture_unix_us, to=requester, at=asked_at: self._reply(done, pts, us, to, at)
            )

    def _localization_request(self, capture_unix_us):
        frame = TargetBoxArray()
        frame.header.stamp = _unix_us_to_stamp(capture_unix_us)
        frame.uav_target_boxes = [_degenerate_box(index, pixel) for index, pixel in enumerate(self.sample_pixels)]
        return TBALocalization.Request(
            un_localized=frame,
            image_width=self.stream_width,
            image_height=self.stream_height,
        )

    def _reply(self, future, frame_pts, capture_unix_us, requester, asked_at):
        self._round_trips_ms.append((time.monotonic() - asked_at) * 1000.0)
        response = future.result()
        if response is None:
            self._record("call did not return")
            return
        if not response.success:
            self._record(_failure_kind(response.message), response.message[:110])
            return
        self._record("localized")
        packet = self.encode(response.localized_boxes, capture_unix_us)
        self._socket.sendto(struct.pack(REPLY_HEADER_FORMAT, frame_pts) + packet, requester)

    def encode(self, frame, capture_unix_us):
        horizontal_fov_deg, vertical_fov_deg = field_of_view_deg(self._camera_info)
        platform_pitch_deg, platform_roll_deg = _aerospace_angles(frame.uav_local_pose.pose.pose.orientation)
        sensor_pitch_deg, sensor_roll_deg = _aerospace_angles(frame.gimbal_attitude_quaternion)
        sensor_heading_deg = _compass_heading(frame.gimbal_attitude_quaternion)
        boxes = frame.uav_target_boxes
        centre = _best_fix(boxes[FRAME_CENTRE_INDEX])
        corners = [_best_fix(boxes[index]) for index in CORNER_INDICES]

        items = [
            (misb.UNIX_TIME_STAMP, capture_unix_us),
            (misb.UAS_LDS_VERSION_NUMBER, misb.UAS_LDS_VERSION),
            (misb.PLATFORM_DESIGNATION, self.platform_designation),
            (misb.IMAGE_SOURCE_SENSOR, self.image_source_sensor),
            (misb.SENSOR_LATITUDE, frame.uav_gps_location.latitude),
            (misb.SENSOR_LONGITUDE, frame.uav_gps_location.longitude),
            (misb.SENSOR_TRUE_ALTITUDE, frame.uav_gps_location.altitude),
            (misb.PLATFORM_HEADING_ANGLE, frame.uav_compass_hdg),
            (misb.PLATFORM_PITCH_ANGLE, platform_pitch_deg),
            (misb.PLATFORM_ROLL_ANGLE, platform_roll_deg),
            (misb.SENSOR_HORIZONTAL_FIELD_OF_VIEW, horizontal_fov_deg),
            (misb.SENSOR_VERTICAL_FIELD_OF_VIEW, vertical_fov_deg),
            (misb.SENSOR_RELATIVE_AZIMUTH_ANGLE, (sensor_heading_deg - frame.uav_compass_hdg) % 360.0),
            (misb.SENSOR_RELATIVE_ELEVATION_ANGLE, sensor_pitch_deg - platform_pitch_deg),
            (misb.SENSOR_RELATIVE_ROLL_ANGLE, (sensor_roll_deg - platform_roll_deg) % 360.0),
        ]
        if frame.rangefinder_dist.range > 0.0:
            items.append((misb.SLANT_RANGE, frame.rangefinder_dist.range))
        if _located(centre):
            items += [
                (misb.FRAME_CENTER_LATITUDE, centre.latitude),
                (misb.FRAME_CENTER_LONGITUDE, centre.longitude),
                (misb.FRAME_CENTER_ELEVATION, centre.altitude),
            ]
        if all(_located(corner) for corner in corners):
            for corner, latitude_field, longitude_field in zip(corners, misb.CORNER_LATITUDE_FIELDS, misb.CORNER_LONGITUDE_FIELDS):
                items.append((latitude_field, corner.latitude))
                items.append((longitude_field, corner.longitude))

        return misb.local_set(*items)


def main():
    rclpy.init()
    responder = GeolocationResponder()
    executor = MultiThreadedExecutor()
    executor.add_node(responder)
    try:
        executor.spin()
    finally:
        responder.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
