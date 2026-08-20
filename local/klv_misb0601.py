#!/usr/bin/env python3
"""MISB ST 0601 UAS Datalink Local Set encoding."""

import struct
from dataclasses import dataclass
from typing import Callable

UAS_DATALINK_LOCAL_SET_KEY = bytes.fromhex("060E2B34020B01010E01030101000000")
UAS_LDS_VERSION = 15

CHECKSUM_TAG = 1
CHECKSUM_LENGTH = 2
MAX_ASCII_LENGTH = 127


def _clamped(value, minimum, maximum):
    return min(max(float(value), minimum), maximum)


def _unsigned_range(minimum, maximum, fmt):
    full_scale = (1 << (8 * struct.calcsize(fmt))) - 1

    def encode(value):
        normalized = (_clamped(value, minimum, maximum) - minimum) / (maximum - minimum)
        return struct.pack(fmt, round(normalized * full_scale))

    return encode


def _signed_range(magnitude, fmt):
    full_scale = (1 << (8 * struct.calcsize(fmt) - 1)) - 1

    def encode(value):
        return struct.pack(fmt, round(_clamped(value, -magnitude, magnitude) / magnitude * full_scale))

    return encode


def _microseconds(value):
    return struct.pack(">Q", int(value))


def _uint8(value):
    return struct.pack(">B", int(value))


def _ascii(value):
    return str(value).encode("ascii", errors="replace")[:MAX_ASCII_LENGTH]


@dataclass(frozen=True)
class Field:
    tag: int
    encode: Callable[[object], bytes]

    def item(self, value):
        payload = self.encode(value)
        return bytes((self.tag, len(payload))) + payload


UNIX_TIME_STAMP = Field(2, _microseconds)
PLATFORM_DESIGNATION = Field(10, _ascii)
IMAGE_SOURCE_SENSOR = Field(11, _ascii)
PLATFORM_HEADING_ANGLE = Field(5, _unsigned_range(0, 360, ">H"))
PLATFORM_PITCH_ANGLE = Field(6, _signed_range(20, ">h"))
PLATFORM_ROLL_ANGLE = Field(7, _signed_range(50, ">h"))
SENSOR_LATITUDE = Field(13, _signed_range(90, ">i"))
SENSOR_LONGITUDE = Field(14, _signed_range(180, ">i"))
SENSOR_TRUE_ALTITUDE = Field(15, _unsigned_range(-900, 19000, ">H"))
SENSOR_HORIZONTAL_FIELD_OF_VIEW = Field(16, _unsigned_range(0, 180, ">H"))
SENSOR_VERTICAL_FIELD_OF_VIEW = Field(17, _unsigned_range(0, 180, ">H"))
SENSOR_RELATIVE_AZIMUTH_ANGLE = Field(18, _unsigned_range(0, 360, ">I"))
SENSOR_RELATIVE_ELEVATION_ANGLE = Field(19, _signed_range(180, ">i"))
SENSOR_RELATIVE_ROLL_ANGLE = Field(20, _unsigned_range(0, 360, ">I"))
SLANT_RANGE = Field(21, _unsigned_range(0, 5000000, ">I"))
FRAME_CENTER_LATITUDE = Field(23, _signed_range(90, ">i"))
FRAME_CENTER_LONGITUDE = Field(24, _signed_range(180, ">i"))
FRAME_CENTER_ELEVATION = Field(25, _unsigned_range(-900, 19000, ">H"))
UAS_LDS_VERSION_NUMBER = Field(65, _uint8)

CORNER_LATITUDE_FIELDS = tuple(Field(tag, _signed_range(90, ">i")) for tag in (82, 84, 86, 88))
CORNER_LONGITUDE_FIELDS = tuple(Field(tag, _signed_range(180, ">i")) for tag in (83, 85, 87, 89))


def _ber_length(length):
    if length < 128:
        return bytes((length,))
    encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes((0x80 | len(encoded),)) + encoded


def local_set(*items):
    """Encode (Field, value) pairs as one checksummed UAS Datalink Local Set packet."""
    body = b"".join(field.item(value) for field, value in items if value is not None)
    body += bytes((CHECKSUM_TAG, CHECKSUM_LENGTH))
    packet = UAS_DATALINK_LOCAL_SET_KEY + _ber_length(len(body) + CHECKSUM_LENGTH) + body
    return packet + struct.pack(">H", sum(packet) % (1 << 16))
