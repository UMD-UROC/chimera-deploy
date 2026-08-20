#!/usr/bin/env python3
"""Projection of a gimballed camera onto the ground plane the aircraft is flying above."""

import math
from dataclasses import dataclass

WGS84_EQUATORIAL_RADIUS_M = 6378137.0
WGS84_ECCENTRICITY_SQUARED = 0.00669437999014
HORIZON_SLANT_RANGE_LIMIT_M = 20000.0
LOOKING_DOWN_EPSILON = 1e-6

BORESIGHT_BODY = (1.0, 0.0, 0.0)
IMAGE_CORNERS_CLOCKWISE_FROM_UPPER_LEFT = ((-1, -1), (1, -1), (1, 1), (-1, 1))


@dataclass(frozen=True)
class GeoPoint:
    latitude_deg: float
    longitude_deg: float


@dataclass(frozen=True)
class Attitude:
    yaw_deg: float
    pitch_deg: float
    roll_deg: float


@dataclass(frozen=True)
class Footprint:
    center: GeoPoint
    slant_range_m: float
    corners: tuple


def _rotation_ned_from_body(attitude):
    yaw, pitch, roll = (math.radians(angle) for angle in (attitude.yaw_deg, attitude.pitch_deg, attitude.roll_deg))
    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)
    cos_roll, sin_roll = math.cos(roll), math.sin(roll)
    return (
        (cos_yaw * cos_pitch, cos_yaw * sin_pitch * sin_roll - sin_yaw * cos_roll, cos_yaw * sin_pitch * cos_roll + sin_yaw * sin_roll),
        (sin_yaw * cos_pitch, sin_yaw * sin_pitch * sin_roll + cos_yaw * cos_roll, sin_yaw * sin_pitch * cos_roll - cos_yaw * sin_roll),
        (-sin_pitch, cos_pitch * sin_roll, cos_pitch * cos_roll),
    )


def _multiplied(outer, inner):
    return tuple(
        tuple(sum(outer[row][axis] * inner[axis][column] for axis in range(3)) for column in range(3))
        for row in range(3)
    )


def _rotated(rotation, vector):
    return tuple(sum(row[axis] * vector[axis] for axis in range(3)) for row in rotation)


def _unit(vector):
    length = math.sqrt(sum(axis * axis for axis in vector))
    return tuple(axis / length for axis in vector)


def _offset_point(origin, north_m, east_m):
    latitude = math.radians(origin.latitude_deg)
    curvature = 1.0 - WGS84_ECCENTRICITY_SQUARED * math.sin(latitude) ** 2
    meridian_radius = WGS84_EQUATORIAL_RADIUS_M * (1.0 - WGS84_ECCENTRICITY_SQUARED) / curvature ** 1.5
    normal_radius = WGS84_EQUATORIAL_RADIUS_M / math.sqrt(curvature)
    return GeoPoint(
        origin.latitude_deg + math.degrees(north_m / meridian_radius),
        origin.longitude_deg + math.degrees(east_m / (normal_radius * math.cos(latitude))),
    )


def _ground_hit(origin, height_above_ground_m, ray_ned):
    north, east, down = ray_ned
    if down <= LOOKING_DOWN_EPSILON:
        return None, None
    slant_range_m = height_above_ground_m / down
    if slant_range_m > HORIZON_SLANT_RANGE_LIMIT_M:
        return None, None
    return _offset_point(origin, slant_range_m * north, slant_range_m * east), slant_range_m


def project(position, height_above_ground_m, gimbal, camera_offset, horizontal_fov_deg, vertical_fov_deg):
    """Ground footprint seen by a camera whose boresight sits at camera_offset within the gimbal frame."""
    rotation = _multiplied(_rotation_ned_from_body(gimbal), _rotation_ned_from_body(camera_offset))
    center, slant_range_m = _ground_hit(position, height_above_ground_m, _rotated(rotation, BORESIGHT_BODY))
    if center is None:
        return None

    half_width = math.tan(math.radians(horizontal_fov_deg) / 2.0)
    half_height = math.tan(math.radians(vertical_fov_deg) / 2.0)
    corners = []
    for right, down in IMAGE_CORNERS_CLOCKWISE_FROM_UPPER_LEFT:
        ray = _unit(_rotated(rotation, (1.0, right * half_width, down * half_height)))
        corner, _ = _ground_hit(position, height_above_ground_m, ray)
        if corner is None:
            corners = []
            break
        corners.append(corner)

    return Footprint(center=center, slant_range_m=slant_range_m, corners=tuple(corners))
