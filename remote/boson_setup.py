#!/usr/bin/env python3
"""Report the Boson's image and radiometry settings, or apply the Chimera ones.

Chimera flies black hot, because the detectors we run do much better on it.
The inversion is the camera's own palette. The Boson applies it to the 8-bit
video after its AGC, so the stream arrives already inverted and every consumer
of thermal-fork gets it. coloreffects preset=xray in the pipeline inverts too,
but also shades the frame blue, and costs a videoconvert on the CPU.

    ./boson_setup.py                     # report, and what --apply would change
    ./boson_setup.py --apply             # apply PROFILE and save it to camera flash
    ./boson_setup.py --apply --no-save   # try it until the camera loses power
    ./boson_setup.py --factory           # back to FLIR's factory settings, saved
    ./boson_setup.py --check             # exit 1 unless it matches PROFILE

Every change shows in the live stream at once. Nothing has to restart.

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

To undo it, --factory loads FLIR's factory settings (white hot and the factory
AGC) and saves them. It keeps the averager as it was. Then --apply puts the
Chimera settings back.

On Chimera v3, also run ./boson_averager.py --on and power cycle the camera.
v3 needs the smart averager to share the USB bus with the C1 PRO, and v2 does
not, so this script leaves the frame rate alone.

The AGC. PROFILE moves two AGC settings, both following the Boson datasheet
(102-2013-40 rev340, section 6.8), to suit black hot and warm people 30-60 m
out, who span 10-20 pixels:

  ACE (agcSetGamma), 0.97 -> 1.03. The factory 0.97 is tuned for white hot,
  where values under 1 give the warm end of the scene more contrast. The
  datasheet says to mirror it around 1 when switching to black hot.

  Linear percent, 20 -> 30. The histogram mapping closes up empty levels, so a
  person in front of something a little cooler can end up a shade or two away
  from it. A more linear mapping keeps them apart; the datasheet's example of
  exactly this uses 30.

Measured on d3's live stream on 2026-09-29, in a bench scene with people in
view, three frames per setting. Linear 30 raised person contrast-to-noise by
8-10% over the factory 20, with slightly less noise on the ground. 50 went
further (16-19%) but flattens the rest of the picture and is past anything
FLIR documents. ACE from 0.90 to 1.10 moved it by less than the frame-to-frame
spread, so FLIR's black hot pairing costs nothing. Max gain 2 made it worse.

The rest stays as FLIR set it for the unit. On d3, the factory header matches
what the camera ran apart from the palette (checked 2026-09-29), including
DDE 1.05 and smoothing 5000 where the datasheet's generic values are 0.95 and
1250. FLIR says to leave the smoothing factor alone. Tail rejection stays at 0:
it would flatten a person into one grey level ("completely washed out", per
FLIR's Camera Adjustments note).

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

GAO_SETAVERAGERSTATE = 0x0000000B
BOSON_RESTOREFACTORYDEFAULTSFROMFLASH = 0x0005001B
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

# What --apply sets. See the docstring for why.
#   (label, get, set, wanted, struct format, names, radiometric cameras only)
PROFILE = [
    # colorLut. The palette only applies while colorization is on.
    ("palette enabled", 0x000B0002, 0x000B0001, 1, ">i", OFF_ON, False),
    ("palette", 0x000B0004, 0x000B0003, 1, ">i", PALETTES, False),
    # agcGamma and agcLinearPercent. Back to 0.97 and 20 for white hot.
    ("ACE (gamma)", 0x0009000E, 0x0009000D, 1.03, ">f", None, False),
    ("linear percent", 0x00090004, 0x00090003, 30.0, ">f", None, False),
    # bosonGain/FFCMode. High is the low noise range. Auto drops to low gain,
    # which reaches hotter scenes at the cost of noise, whenever enough of the
    # frame is hot. Auto FFC because nothing on the drone triggers one.
    ("gain mode", 0x00050015, 0x00050014, 0, ">i", GAIN_MODES, False),
    ("FFC mode", 0x00050013, 0x00050012, 1, ">i", FFC_MODES, False),
    # tf, spnr, scnr: the noise filters, on as they ship.
    ("temporal filter", 0x000A0002, 0x000A0001, 1, ">i", OFF_ON, False),
    ("spatial filter", 0x000C0002, 0x000C0001, 1, ">i", OFF_ON, False),
    ("column filter", 0x00080002, 0x00080001, 1, ">i", OFF_ON, False),
    # Makes Y16 frames linear in temperature. Does nothing to the 8-bit video.
    ("TLinear", 0x003E0002, 0x003E0001, 1, ">i", OFF_ON, True),
]

# Reported, never set: the rest of the AGC. (label, get, struct format)
AGC = [
    ("plateau (percentPerBin)", 0x00090002, ">f"),
    ("outlierCut", 0x00090006, ">f"),
    ("maxGain", 0x0009000A, ">f"),
    ("damping (df)", 0x0009000C, ">f"),
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


def same(value, wanted):
    # Floats come back as float32: 1.03 reads 1.0299999713897705.
    if value is None:
        return False
    if isinstance(wanted, float):
        return abs(value - wanted) < 1e-3
    return value == wanted


def name(names, value):
    if value is None:
        return "no answer"
    if isinstance(value, float):
        return f"{value:g}"
    return names.get(value, str(value)) if names else str(value)


def settings(capable):
    return [s for s in PROFILE if capable or not s[6]]


def snapshot(camera, capable):
    return {s[0]: get(camera, s[1], s[4]) for s in settings(capable)}


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
    now = snapshot(camera, capable)
    for label, _, _, wanted, _, names, _ in settings(capable):
        mark = "" if same(now[label], wanted) else "   <- changes"
        print(f"{label:18s}{name(names, now[label]):14s}{name(names, wanted)}{mark}")

    print()
    print("Rest of the AGC, as FLIR set it (--apply leaves it alone):")
    for label, get_fid, fmt in AGC:
        value = get(camera, get_fid, fmt)
        print(f"  {label:24s}{name(OFF_ON if fmt == '>i' else None, value)}")
    return 0


def save_or_not(camera, save):
    if save:
        # bosonWriteDynamicHeaderToFlash
        camera.set_pwr_on_defaults()
        print("Saved to camera flash. It survives a power cycle.")
    else:
        print("Not saved. The camera goes back to its flash settings when it loses power.")


def apply(camera, capable, save):
    changed = []
    for label, get_fid, set_fid, wanted, fmt, names, _ in settings(capable):
        now = get(camera, get_fid, fmt)
        if same(now, wanted):
            continue
        camera._send_packet(set_fid, data=struct.pack(fmt, wanted))
        # flirpy only logs a refusal, so read it back.
        readback = get(camera, get_fid, fmt)
        if not same(readback, wanted):
            print(f"error: {label}: set {name(names, wanted)}, camera reports {name(names, readback)}",
                  file=sys.stderr)
            return 1
        changed.append(f"{label} {name(names, now)} -> {name(names, wanted)}")

    for line in changed:
        print(line)
    if not changed:
        print("Already set.")
    # Saved even when nothing changed: an earlier --no-save run may have left
    # the camera ahead of its flash.
    save_or_not(camera, save)
    return 0


def factory(camera, capable, save):
    before = snapshot(camera, capable)
    averager = camera.get_averager()
    camera._send_packet(BOSON_RESTOREFACTORYDEFAULTSFROMFLASH)
    # The factory averager is off, which on v3 costs the thermal camera its
    # place on the USB bus. boson_averager.py owns it, so put it back.
    if camera.get_averager() != averager:
        camera._send_packet(GAO_SETAVERAGERSTATE, data=struct.pack(">i", averager))
    after = snapshot(camera, capable)

    names = {s[0]: s[5] for s in PROFILE}
    for label, value in after.items():
        if not same(value, before[label]):
            print(f"{label} {name(names[label], before[label])} -> {name(names[label], value)}")
    save_or_not(camera, save)
    return 0


def check(camera, capable):
    now = snapshot(camera, capable)
    off = [f"{label} is {name(names, now[label])}, want {name(names, wanted)}"
           for label, _, _, wanted, _, names, _ in settings(capable) if not same(now[label], wanted)]
    print("; ".join(off) if off else "matches PROFILE")
    return 1 if off else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="apply PROFILE and save it to flash")
    action.add_argument("--factory", action="store_true",
                        help="restore FLIR's factory settings, except the averager, and save them")
    action.add_argument("--check", action="store_true",
                        help="exit 1 unless the camera matches PROFILE (deploy_doctor.sh uses this)")
    parser.add_argument("--no-save", action="store_true", help="with --apply or --factory, leave flash alone")
    parser.add_argument("--port", help="serial port (default: found by USB id)")
    args = parser.parse_args()
    if args.no_save and not (args.apply or args.factory):
        parser.error("--no-save only goes with --apply or --factory")

    camera = open_camera(args.port)
    try:
        capable = radiometric(camera)
        if args.apply:
            return apply(camera, capable, save=not args.no_save)
        if args.factory:
            return factory(camera, capable, save=not args.no_save)
        if args.check:
            return check(camera, capable)
        return report(camera, capable)
    finally:
        camera.close()


if __name__ == "__main__":
    sys.exit(main())
