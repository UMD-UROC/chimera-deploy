#!/usr/bin/env python3
"""Resolve V4L2 nodes by card name and pixel format instead of by index.

/dev/videoN numbering is not stable once more than one USB camera is on the
bus: the C1 PRO claims four nodes (encoded capture, raw capture and two
metadata nodes) and the Boson claims two, so the thermal camera moves as soon
as a camera is added, removed or re-enumerated in a different order.

Matching on the card name plus an advertised pixel format is stable, and it is
also what lets us tell the C1 PRO's H.264 node apart from its MJPEG node --
both report the same card name.
"""

import fcntl
import glob
import os
import struct

V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_BUF_TYPE_VIDEO_CAPTURE = 1

# _IOR('V', 0, struct v4l2_capability), _IOWR('V', 2, struct v4l2_fmtdesc)
VIDIOC_QUERYCAP = 0x80685600
VIDIOC_ENUM_FMT = 0xC0405602

# driver[16] card[32] bus_info[32] version capabilities device_caps reserved[3]
_CAPABILITY = struct.Struct("16s32s32sIII12x")
# index type flags description[32] pixelformat mbus_code reserved[3]
_FMTDESC = struct.Struct("III32sII12x")


def fourcc(code):
    """'MJPG' -> the packed V4L2 pixel format integer."""
    a, b, c, d = code.ljust(4)[:4]
    return ord(a) | (ord(b) << 8) | (ord(c) << 16) | (ord(d) << 24)


def _cstr(raw):
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _node_index(path):
    digits = "".join(ch for ch in os.path.basename(path) if ch.isdigit())
    return int(digits) if digits else -1


def _query_cap(fd):
    buf = bytearray(_CAPABILITY.size)
    fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
    _driver, card, bus_info, _version, caps, device_caps = _CAPABILITY.unpack(bytes(buf))
    # device_caps describes this node; caps describes the whole physical device.
    return _cstr(card), _cstr(bus_info), (device_caps or caps)


def _capture_formats(fd):
    formats = []
    for index in range(32):
        buf = bytearray(_FMTDESC.pack(index, V4L2_BUF_TYPE_VIDEO_CAPTURE, 0, b"", 0, 0))
        try:
            fcntl.ioctl(fd, VIDIOC_ENUM_FMT, buf)
        except OSError:
            break
        formats.append(_FMTDESC.unpack(bytes(buf))[4])
    return formats


def list_capture_devices():
    """[(path, card, bus_info, ['MJPG', ...]), ...] for every capture node."""
    devices = []
    for path in sorted(glob.glob("/dev/video*"), key=_node_index):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            card, bus_info, caps = _query_cap(fd)
            if not caps & V4L2_CAP_VIDEO_CAPTURE:
                continue
            formats = _capture_formats(fd)
        except OSError:
            continue
        finally:
            os.close(fd)

        names = []
        for value in formats:
            names.append(
                bytes(
                    (value >> shift) & 0xFF for shift in (0, 8, 16, 24)
                ).decode("ascii", "replace")
            )
        devices.append((path, card, bus_info, names))
    return devices


def find_device(card_match, pixelformat=None, env_var=None, required=True):
    """Lowest-numbered capture node whose card name contains card_match.

    pixelformat ('H264', 'MJPG', ...) further narrows the match, which is how
    the C1 PRO's encoded node is picked over its raw one. Setting env_var
    pins the path by hand and skips the search entirely.

    Missing camera raises RuntimeError; pass required=False to get None back
    instead, for callers that would rather drop the stream than refuse to run.
    """
    if env_var:
        override = os.environ.get(env_var)
        if override:
            return override

    devices = list_capture_devices()
    needle = card_match.lower()

    for path, card, _bus_info, formats in devices:
        if needle not in card.lower():
            continue
        if pixelformat is not None and pixelformat not in formats:
            continue
        return path

    if not required:
        return None

    detail = "\n".join(
        f"  {path}  card={card!r}  formats={','.join(formats) or '-'}"
        for path, card, _bus_info, formats in devices
    )
    wanted = f"{card_match!r}" + (f" with format {pixelformat!r}" if pixelformat else "")
    hint = f" (set {env_var} to override)" if env_var else ""
    raise RuntimeError(
        f"No V4L2 capture device matching {wanted}{hint}.\nAvailable:\n{detail or '  (none)'}"
    )


if __name__ == "__main__":
    for path, card, bus_info, formats in list_capture_devices():
        print(f"{path}\t{card}\t{bus_info}\t{','.join(formats)}")
