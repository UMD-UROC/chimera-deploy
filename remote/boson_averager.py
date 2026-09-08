#!/usr/bin/env python3
"""Read or set the Boson smart averager, which is the camera frame rate control.

The Boson is the only camera on the USB bus with a bulk endpoint, so it reserves
no bandwidth and takes only what the C1 PRO's isochronous stream leaves. At
60 Hz it asks for 29 MB/s, the C1 PRO holds 19.2 at 1080p, and the bus carries
about 40. The thermal camera loses that fight and drops off the bus in under two
minutes.

The UVC frame interval does not help. The camera accepts 30 fps, reports it back
through VIDIOC_G_PARM, and keeps sending 60 Hz. Measured on d1, 2026-09-08.

The averager is the real control. The FLIR Boson IDD, Rev205v2, describes
gaoSetAveragerState as "a smart-averager function which cuts frame rate in
half", and there is no sysctrlSetCameraFrameRate to go with the getter. With it
on, the camera sends 29.7 fps and 14.6 MB/s, and both cameras fit.

    ./boson_averager.py              # report
    ./boson_averager.py --on         # halve the frame rate, then power cycle
    ./boson_averager.py --off        # back to 60 Hz, then power cycle

Needs flirpy:  python3 -m pip install --user flirpy
"""

import argparse
import struct
import sys

# FLIR Boson Software IDD, 102-2013-42 Rev205v2.
FID_GET_CAMERA_FRAME_RATE = 0x000E0007  # sysctrlGetCameraFrameRate
FID_WRITE_DYNAMIC_HEADER = 0x00050018   # bosonWriteDynamicHeaderToFlash

DEFAULT_PORT = "/dev/ttyACM0"


def open_camera(port):
    try:
        from flirpy.camera.boson import Boson
    except ImportError:
        sys.exit("flirpy is not installed. python3 -m pip install --user flirpy")
    return Boson(port=port)


def frame_rate(camera):
    """What the camera says it runs at: 60, 30 or 9."""
    packet = camera._send_packet(FID_GET_CAMERA_FRAME_RATE, receive_size=4)
    payload = camera._decode_packet(packet, receive_size=4)
    if payload is None or len(payload) != 4:
        return None
    return struct.unpack(">I", payload)[0]


def report(camera):
    rate = frame_rate(camera)
    averager = camera.get_averager()
    print(f"part number : {camera.get_part_number().strip()}")
    print(f"serial      : {camera.get_camera_serial()}")
    print(f"firmware    : {camera.get_firmware_revision()}")
    print(f"FPA temp C  : {camera.get_fpa_temperature()}")
    print(f"averager    : {averager}  (1 halves the frame rate)")
    print(f"frame rate  : {rate} fps")
    if rate == 60:
        print()
        print("WARNING: 60 Hz thermal is 29 MB/s and does not fit next to the")
        print("C1 PRO at 1080p. Run --on, then power cycle, or the thermal")
        print("camera will leave the USB bus within about 90 seconds.")
    return 0 if rate is not None else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--on", action="store_true", help="halve the frame rate")
    group.add_argument("--off", action="store_true", help="restore 60 Hz")
    parser.add_argument("--port", default=DEFAULT_PORT)
    args = parser.parse_args()

    camera = open_camera(args.port)
    try:
        if not (args.on or args.off):
            return report(camera)

        wanted = 1 if args.on else 0
        # set_averager already writes the dynamic header, but say so out loud:
        # this is non volatile, and it is why a power cycle is needed.
        camera.set_averager(wanted)
        camera._send_packet(FID_WRITE_DYNAMIC_HEADER)
        print(f"averager set to {wanted} and written to camera flash.")
        print("It does NOT take effect until the camera loses power. A reboot")
        print("of the Orin is not enough, the camera itself has to go down.")
        print("Afterwards check with: ./boson_averager.py")
        return 0
    finally:
        camera.close()


if __name__ == "__main__":
    sys.exit(main())
