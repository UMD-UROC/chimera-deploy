#!/usr/bin/env python3
"""Report the Boson's image and radiometry settings, or apply the Chimera ones.

Chimera flies black hot, and the inversion is the camera's own palette. The
Boson applies it to the 8-bit video after its AGC, so the stream arrives
already inverted and every consumer of thermal-fork gets it. coloreffects
preset=xray in the pipeline inverts too, but also shades the frame blue, and
costs a videoconvert on the CPU.

    ./boson_setup.py                     # report, and what --apply would change
    ./boson_setup.py --apply             # apply PROFILE and save it to camera flash
    ./boson_setup.py --apply --no-save   # try it until the camera loses power

The palette changes the live stream at once. Nothing has to restart.

Setting up a drone. The settings live in the camera, so this is once per
camera, and again after a camera swap:

    python3 -m pip install --user pyserial==3.5           # deploy.sh does these two
    python3 -m pip install --user --no-deps flirpy==0.6.2
    ./boson_setup.py                                      # after sync, in ~/chimera-deploy/remote
    ./boson_setup.py --apply

--no-deps matters. flirpy asks for pip's opencv-python-headless, which needs
numpy 2 (deploy.sh pins numpy<2 for torch) and would shadow JetPack's cv2, the
one built with GStreamer. flirpy's Boson class needs only cv2 and pyserial,
and JetPack already has cv2.

On Chimera v3, also run ./boson_averager.py --on and power cycle the camera.
v3 needs the smart averager to share the USB bus with the C1 PRO, and v2 does
not, so this script leaves the frame rate alone.

It also leaves the AGC alone. A camera arrives with FLIR's tuning for its
model and lens. The IDD says sigmaR "should be proportional to imager
responsivity", so one camera's numbers are not an improvement on another's.
The report prints them, so a change can be made on purpose, in PROFILE, after
looking at flight footage.

Radiometry. Only part numbers with an R second to last have it. d3's
20640A032-6IARX does, and arrived with it running (TLinear on). None of it
reaches the stream: the 8-bit video is AGC mapped and carries no temperature.
Temperatures come out as 16-bit Y16 frames, which the camera sends instead of
the 8-bit video, not as well. Using them means switching thermal-fork to Y16
and doing the AGC on the Orin, which is pipeline work, not a camera setting.

Function codes and payloads come from the FLIR Boson SDK (FunctionCodes.h,
Client_Packager.c) and the Boson+ Software IDD, 102-2013-42 rev410. flirpy
wraps only a few of them, so the rest go through its _send_packet, as in
boson_averager.py.
"""

import argparse
import logging
import struct
import sys

SYSCTRL_GETCAMERAFRAMERATE = 0x000E0007
RADIOMETRY_GETRADIOMETRYCAPABLE = 0x0042007D

OFF_ON = {0: "off", 1: "on"}
PALETTES = {
    0: "white hot", 1: "black hot", 2: "rainbow", 3: "rainbow HC",
    4: "ironbow", 5: "lava", 6: "arctic", 7: "globow", 8: "graded fire",
    9: "hottest",
}
GAIN_MODES = {0: "high", 1: "low", 2: "auto", 3: "dual", 4: "manual"}
FFC_MODES = {0: "manual", 1: "auto", 2: "external", 3: "shutter test"}

# What --apply sets. Every value is a 4-byte enum.
#   (label, get, set, wanted, names, radiometric cameras only)
PROFILE = [
    # colorLut. The palette only applies while colorization is on.
    ("palette enabled", 0x000B0002, 0x000B0001, 1, OFF_ON, False),
    ("palette", 0x000B0004, 0x000B0003, 1, PALETTES, False),
    # bosonGain/FFCMode. High is the low noise range. Auto drops to low gain,
    # which reaches hotter scenes at the cost of noise, whenever enough of the
    # frame is hot. Auto FFC because nothing on the drone triggers one.
    ("gain mode", 0x00050015, 0x00050014, 0, GAIN_MODES, False),
    ("FFC mode", 0x00050013, 0x00050012, 1, FFC_MODES, False),
    # tf, spnr, scnr: the noise filters, on as they ship.
    ("temporal filter", 0x000A0002, 0x000A0001, 1, OFF_ON, False),
    ("spatial filter", 0x000C0002, 0x000C0001, 1, OFF_ON, False),
    ("column filter", 0x00080002, 0x00080001, 1, OFF_ON, False),
    # Makes Y16 frames linear in temperature. Does nothing to the 8-bit video.
    ("TLinear", 0x003E0002, 0x003E0001, 1, OFF_ON, True),
]

# Reported, never set. (label, get, struct format)
AGC = [
    ("plateau (percentPerBin)", 0x00090002, ">f"),
    ("linearPercent", 0x00090004, ">f"),
    ("outlierCut", 0x00090006, ">f"),
    ("maxGain", 0x0009000A, ">f"),
    ("damping (df)", 0x0009000C, ">f"),
    ("gamma", 0x0009000E, ">f"),
    ("detailHeadroom", 0x00090014, ">f"),
    ("DDE (d2br)", 0x00090016, ">f"),
    ("sigmaR", 0x00090018, ">f"),
    ("useEntropy", 0x0009001F, ">i"),
    ("ROI rows, cols", 0x00090021, ">HHHH"),
]

INSTALL = """flirpy is not installed. On the drone:
    python3 -m pip install --user pyserial==3.5
    python3 -m pip install --user --no-deps flirpy==0.6.2"""


def open_camera(port):
    try:
        import serial
        from flirpy.camera.boson import Boson
    except ImportError:
        sys.exit(INSTALL)
    # By USB id, not /dev/ttyACM0: on some drones that is the flight controller.
    port = port or Boson.find_serial_device()
    if port is None:
        sys.exit("No Boson on USB (09cb:4007). Otherwise pass --port.")
    try:
        return Boson(port=port)
    except serial.SerialException as error:
        sys.exit(f"{error}. The user needs to be in the dialout group.")


def get(camera, fid, fmt=">i"):
    """A getter flirpy has no method for. None if the camera refused it."""
    size = struct.calcsize(fmt)
    payload = camera._decode_packet(camera._send_packet(fid, receive_size=size), receive_size=size)
    if payload is None or len(payload) < size:
        return None
    values = struct.unpack(fmt, payload[:size])
    return values[0] if len(values) == 1 else values


def radiometric(camera):
    # Firmware without the radiometry module answers "bad command ID", which
    # flirpy would log as a warning.
    level = camera.logger.level
    camera.logger.setLevel(logging.ERROR)
    try:
        return get(camera, RADIOMETRY_GETRADIOMETRYCAPABLE) == 1
    finally:
        camera.logger.setLevel(level)


def name(names, value):
    if value is None:
        return "no answer"
    return names.get(value, str(value))


def settings(capable):
    return [s for s in PROFILE if capable or not s[5]]


def report(camera, capable):
    major, minor, patch = camera.get_firmware_revision()
    # FLIR pads these strings with NULs, which turn the output into a "binary
    # file" as far as grep is concerned.
    part = camera.get_part_number().replace("\x00", "").strip()
    print(f"camera       {part}  sn {camera.get_camera_serial()}  firmware {major}.{minor}.{patch}")
    print(f"FPA temp     {camera.get_fpa_temperature():.1f} C")
    rate = get(camera, SYSCTRL_GETCAMERAFRAMERATE, ">I")
    print(f"frame rate   {rate} fps, averager {name(OFF_ON, camera.get_averager())} (./boson_averager.py)")
    print(f"radiometric  {'yes' if capable else 'no'}")

    print()
    print(f"{'':18s}{'camera':14s}--apply")
    for label, get_fid, _, wanted, names, _ in settings(capable):
        now = get(camera, get_fid)
        mark = "" if now == wanted else "   <- changes"
        print(f"{label:18s}{name(names, now):14s}{name(names, wanted)}{mark}")

    print()
    print("AGC as the camera has it (--apply leaves it alone):")
    for label, get_fid, fmt in AGC:
        value = get(camera, get_fid, fmt)
        if value is not None and fmt == ">f":
            value = f"{value:g}"
        elif fmt == ">i":
            value = name(OFF_ON, value)
        print(f"  {label:24s}{value}")
    return 0


def apply(camera, capable, save):
    changed = []
    for label, get_fid, set_fid, wanted, names, _ in settings(capable):
        now = get(camera, get_fid)
        if now == wanted:
            continue
        camera._send_packet(set_fid, data=struct.pack(">i", wanted))
        # flirpy only logs a refusal, so read it back.
        readback = get(camera, get_fid)
        if readback != wanted:
            print(f"error: {label}: set {name(names, wanted)}, camera reports {name(names, readback)}",
                  file=sys.stderr)
            return 1
        changed.append(f"{label} {name(names, now)} -> {name(names, wanted)}")

    for line in changed:
        print(line)
    if not changed:
        print("Already set. Nothing written.")
    elif save:
        # bosonWriteDynamicHeaderToFlash
        camera.set_pwr_on_defaults()
        print("Saved to camera flash. It survives a power cycle.")
    else:
        print("Not saved. The camera goes back to its flash settings when it loses power.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="apply PROFILE and save it to flash")
    parser.add_argument("--no-save", action="store_true", help="with --apply, leave flash alone")
    parser.add_argument("--port", help="serial port (default: found by USB id)")
    args = parser.parse_args()
    if args.no_save and not args.apply:
        parser.error("--no-save only goes with --apply")

    camera = open_camera(args.port)
    try:
        capable = radiometric(camera)
        if args.apply:
            return apply(camera, capable, save=not args.no_save)
        return report(camera, capable)
    finally:
        camera.close()


if __name__ == "__main__":
    sys.exit(main())
