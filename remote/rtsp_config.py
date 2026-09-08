# config.py

import os

from v4l2_devices import find_device

# ----------------------------------------
# PILOT (IMX477 CSI camera -- this was previously "rgb")
# ----------------------------------------
PILOT_WIDTH = 3840
PILOT_HEIGHT = 2160
PILOT_FRAMERATE = "30/1"
# PILOT_WIDTH = 1920
# PILOT_HEIGHT = 1080
# PILOT_FRAMERATE = "60/1"
PILOT_BITRATE = 200000000 # nv recording bitrate set in record_nv_streams.sh
PILOT_FLIP_METHOD = 2

PILOT_LOWRES_WIDTH = 640
PILOT_LOWRES_HEIGHT = 360
PILOT_LOWRES_BITRATE = 1000000

# ----------------------------------------
# RGB (C1 PRO USB zoom camera)
# ----------------------------------------
# The C1 PRO only hands out compressed video, so unlike the CSI and thermal
# producers this one has to decode before it can share NVMM buffers. It splits
# its two encodings across two nodes: H.264 and MJPEG. H.264 is the default
# because it costs far less USB bandwidth at 1080p; set RGB_SOURCE=mjpeg to
# use the other node instead.
RGB_SOURCE = os.environ.get("RGB_SOURCE", "h264").lower()
if RGB_SOURCE not in ("h264", "mjpeg"):
    raise RuntimeError(f"RGB_SOURCE must be 'h264' or 'mjpeg', got {RGB_SOURCE!r}")
# Full 1080p30. This is only safe because the Boson now runs at 30 Hz.
#
# Both USB cameras share one high speed bus. The C1 PRO is isochronous and
# reserves its share before anything else runs, and the resolution picks the
# alternate setting that decides how much. The Boson is bulk and lives on the
# remainder. Measured on d1, 2026-09-08:
#
#   C1 PRO mode    alt   reserved     with a 60 Hz Boson   with a 30 Hz Boson
#   1920x1080@30   5     19.2 MB/s    died at 83 s         survived 180 s
#   1920x1080@15   5     19.2 MB/s    not measured         not measured
#   1920x1080@10   3     6.4 MB/s     survived 150 s       not measured
#   720x576@30     3     6.4 MB/s     survived 150 s       not measured
#   640x480@30     3     6.4 MB/s     survived 120 s       not measured
#
# Frame rate moves the reservation only between 15 and 10 fps, so there is no
# point trimming it above that. Resolution is the lever.
#
# WARNING: if the Boson's averager is off, this setting kills the thermal
# camera in about 90 seconds. A replacement camera arrives with it off. Check
# with `./boson_averager.py` before flying a camera this machine has not seen.
RGB_WIDTH = int(os.environ.get("RGB_WIDTH", 1920))
RGB_HEIGHT = int(os.environ.get("RGB_HEIGHT", 1080))
RGB_FRAMERATE = os.environ.get("RGB_FRAMERATE", "30/1")
RGB_BITRATE = 20000000 # nv recording bitrate set in record_nv_streams.sh
RGB_FLIP_METHOD = 0

RGB_LOWRES_WIDTH = 640
RGB_LOWRES_HEIGHT = 360
RGB_LOWRES_BITRATE = 1000000

# ----------------------------------------
# THERMAL (Boson 640)
# ----------------------------------------
THERMAL_WIDTH = 640
THERMAL_HEIGHT = 512
THERMAL_BITRATE = 8000000 # nv recording bitrate set in record_nv_streams.sh

# 30, to match what the camera really sends once its smart averager is on.
#
# This buys no bandwidth on its own. The Boson ignores the UVC frame interval:
# ask for 30 and VIDIOC_G_PARM reports 30 while 59 fps keeps arriving. What
# makes the camera slow down is `boson_averager.py --on`, which is a setting in
# the camera flash, not here. Measured on d1, 2026-09-08:
#
#   averager off, no caps rate    59.1 fps    29.0 MB/s
#   averager off, caps say 30/1   59.1 fps    29.0 MB/s   <- the knob does nothing
#   averager on,  no caps rate    29.7 fps    14.6 MB/s   G_PARM lies, says 60
#   averager on,  caps say 30/1   29.9 fps    14.6 MB/s   G_PARM agrees, says 30
#
# So this line exists to stop the pipeline believing in frames that never come.
# Without it the encoders time 30 Hz video against a 60 Hz clock.
THERMAL_FRAMERATE = os.environ.get("THERMAL_FRAMERATE", "30/1")

# THERMAL_LOWRES_WIDTH = 640
# THERMAL_LOWRES_HEIGHT = 512
THERMAL_LOWRES_WIDTH = THERMAL_WIDTH
THERMAL_LOWRES_HEIGHT = THERMAL_HEIGHT
THERMAL_LOWRES_BITRATE = 400000

# ----------------------------------------
# DEVICE NODES
# ----------------------------------------
# Resolved by card name so the two USB cameras can shuffle /dev/videoN between
# boots without breaking anything. Set RGB_DEVICE / THERMAL_DEVICE to pin them.
# A camera that is unplugged or still enumerating comes back as None: its
# streams get pruned below so the server still serves whatever else is up.
RGB_DEVICE = find_device(
    "C1 PRO",
    "H264" if RGB_SOURCE == "h264" else "MJPG",
    env_var="RGB_DEVICE",
    required=False,
)
THERMAL_DEVICE = find_device("Boson", env_var="THERMAL_DEVICE", required=False)

PILOT = "pilot"
PILOT_DEEPSTREAM = "pilotds"
PILOT_LOWRES = "pilotl"
PILOT_RAW = "pilotraw"
RGB = "rgb"
RGB_DEEPSTREAM = "rgbds"
RGB_LOWRES = "rgbl"
RGB_RAW = "rgbraw"
THERMAL = "thermal"
THERMAL_DEEPSTREAM = "thermalds"
THERMAL_LOWRES = "thermall"
THERMAL_RAW = "thermalraw"

def SOCKET(tag):
    return f"/tmp/{tag}_nv.sock"

SOCKETS = {
    PILOT: SOCKET(PILOT),
    PILOT_DEEPSTREAM: SOCKET(PILOT_DEEPSTREAM),
    PILOT_LOWRES: SOCKET(PILOT_LOWRES),
    PILOT_RAW: SOCKET(PILOT_RAW),
    RGB: SOCKET(RGB),
    RGB_DEEPSTREAM: SOCKET(RGB_DEEPSTREAM),
    RGB_LOWRES: SOCKET(RGB_LOWRES),
    RGB_RAW: SOCKET(RGB_RAW),
    THERMAL: SOCKET(THERMAL),
    THERMAL_DEEPSTREAM: SOCKET(THERMAL_DEEPSTREAM),
    THERMAL_LOWRES: SOCKET(THERMAL_LOWRES),
    THERMAL_RAW: SOCKET(THERMAL_RAW),
}

if RGB_SOURCE == "h264":
    RGB_DECODE = f"""
        video/x-h264,width={RGB_WIDTH},height={RGB_HEIGHT},framerate={RGB_FRAMERATE} !
        h264parse !
        video/x-h264,stream-format=byte-stream,alignment=au !
        nvv4l2decoder enable-max-performance=1 !
        """
else:
    RGB_DECODE = f"""
        image/jpeg,width={RGB_WIDTH},height={RGB_HEIGHT},framerate={RGB_FRAMERATE} !
        jpegparse !
        nvv4l2decoder mjpeg=1 enable-max-performance=1 !
        """

THERMAL_CAPS_RATE = f",framerate={THERMAL_FRAMERATE}" if THERMAL_FRAMERATE else ""

PRODUCERS = {
    "pilot-fork": f"""
        nvarguscamerasrc sensor-id=0 wbmode=1 do-timestamp=true !
        video/x-raw(memory:NVMM),width={PILOT_WIDTH},height={PILOT_HEIGHT},framerate={PILOT_FRAMERATE} !
        nvvidconv flip-method={PILOT_FLIP_METHOD} interpolation-method=1 !
        video/x-raw(memory:NVMM),format=NV12 !
        tee name=t

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={PILOT_WIDTH},height={PILOT_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[PILOT]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={PILOT_WIDTH},height={PILOT_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[PILOT_DEEPSTREAM]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={PILOT_LOWRES_WIDTH},height={PILOT_LOWRES_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[PILOT_LOWRES]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={PILOT_LOWRES_WIDTH},height={PILOT_LOWRES_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[PILOT_RAW]} sync=false async=false
        """,
    "rgb-fork": f"""
        v4l2src device={RGB_DEVICE} io-mode=2 do-timestamp=true !
        {RGB_DECODE.strip()}
        nvvidconv flip-method={RGB_FLIP_METHOD} interpolation-method=1 !
        video/x-raw(memory:NVMM),format=NV12 !
        tee name=t

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={RGB_WIDTH},height={RGB_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[RGB]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={RGB_WIDTH},height={RGB_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[RGB_DEEPSTREAM]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={RGB_LOWRES_WIDTH},height={RGB_LOWRES_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[RGB_LOWRES]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={RGB_LOWRES_WIDTH},height={RGB_LOWRES_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[RGB_RAW]} sync=false async=false
        """,
    "thermal-fork": f"""
        v4l2src device={THERMAL_DEVICE} io-mode=2 do-timestamp=true !
        video/x-raw,width={THERMAL_WIDTH},height={THERMAL_HEIGHT},format=I420{THERMAL_CAPS_RATE} !
        nvvidconv !
        video/x-raw(memory:NVMM),format=NV12 !
        tee name=t

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={THERMAL_WIDTH},height={THERMAL_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[THERMAL]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={THERMAL_WIDTH},height={THERMAL_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[THERMAL_DEEPSTREAM]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={THERMAL_LOWRES_WIDTH},height={THERMAL_LOWRES_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[THERMAL_LOWRES]} sync=false async=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={THERMAL_LOWRES_WIDTH},height={THERMAL_LOWRES_HEIGHT},format=NV12 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={SOCKETS[THERMAL_RAW]} sync=false async=false
        """,
}

FACTORIES = {
    PILOT: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[PILOT]} num-extra-surfaces=4 do-timestamp=true !
        video/x-raw(memory:NVMM),format=NV12,width={PILOT_WIDTH},height={PILOT_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate={PILOT_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
    PILOT_LOWRES: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[PILOT_LOWRES]} num-extra-surfaces=4 do-timestamp=true !
        video/x-raw(memory:NVMM),format=NV12,width={PILOT_LOWRES_WIDTH},height={PILOT_LOWRES_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate={PILOT_LOWRES_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
    RGB: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[RGB]} num-extra-surfaces=4 do-timestamp=true !
        video/x-raw(memory:NVMM),format=NV12,width={RGB_WIDTH},height={RGB_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate={RGB_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
    RGB_LOWRES: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[RGB_LOWRES]} num-extra-surfaces=4 do-timestamp=true !
        video/x-raw(memory:NVMM),format=NV12,width={RGB_LOWRES_WIDTH},height={RGB_LOWRES_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate={RGB_LOWRES_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
    THERMAL: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[THERMAL]} num-extra-surfaces=4 do-timestamp=true !
        video/x-raw(memory:NVMM),format=NV12,width={THERMAL_WIDTH},height={THERMAL_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate={THERMAL_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
    THERMAL_LOWRES: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[THERMAL_LOWRES]} num-extra-surfaces=4 do-timestamp=true !
        video/x-raw(memory:NVMM),format=NV12,width={THERMAL_LOWRES_WIDTH},height={THERMAL_LOWRES_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate={THERMAL_LOWRES_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
}

# What each producer owns, so a camera that is not there takes exactly its own
# streams with it and nothing else. The server reads this at runtime too: a
# camera that dies mid flight has to be taken off the air the same way one that
# never arrived is kept off it.
CAMERA_GROUPS = {
    "pilot-fork": {
        "card": "CSI",
        "factories": [PILOT, PILOT_LOWRES],
        "sockets": [PILOT, PILOT_DEEPSTREAM, PILOT_LOWRES, PILOT_RAW],
    },
    "rgb-fork": {
        "card": "C1 PRO",
        "factories": [RGB, RGB_LOWRES],
        "sockets": [RGB, RGB_DEEPSTREAM, RGB_LOWRES, RGB_RAW],
    },
    "thermal-fork": {
        "card": "Boson",
        "factories": [THERMAL, THERMAL_LOWRES],
        "sockets": [THERMAL, THERMAL_DEEPSTREAM, THERMAL_LOWRES, THERMAL_RAW],
    },
}

# Drop the pipelines that reference a camera we are not going to run. SOCKETS is
# left whole so the server still clears stale socket files for those streams.
# Each entry is (card, reason), because a camera that was left out on purpose
# and one that never showed up are different things to read in a journal.
PRUNED_CAMERAS = []

# Short name for each producer, for RCAM_CAMERAS below.
CAMERA_KEYS = {
    "pilot": "pilot-fork",
    "rgb": "rgb-fork",
    "thermal": "thermal-fork",
}


def _prune(producer, reason):
    group = CAMERA_GROUPS[producer]
    PRUNED_CAMERAS.append((group["card"], reason))
    del PRODUCERS[producer]
    for factory in group["factories"]:
        FACTORIES.pop(factory, None)


if RGB_DEVICE is None:
    _prune("rgb-fork", "no capture device found")

if THERMAL_DEVICE is None:
    _prune("thermal-fork", "no capture device found")

# Run only the named cameras. The USB cameras share one bus powered hub, so a
# camera can be healthy on its own and still fail next to another one. Naming a
# subset takes the others off the bus without touching a cable, which is how
# that kind of fault gets narrowed down on an aircraft nobody can reach.
#
#   RCAM_CAMERAS=thermal          only the Boson
#   RCAM_CAMERAS=thermal,rgb      the Boson and the C1 PRO, no CSI
_wanted = os.environ.get("RCAM_CAMERAS", "")
if _wanted.strip():
    _keep = {name.strip().lower() for name in _wanted.split(",") if name.strip()}
    _unknown = _keep - set(CAMERA_KEYS)
    if _unknown:
        raise RuntimeError(
            f"RCAM_CAMERAS names {sorted(_unknown)}, which are not cameras. "
            f"Pick from {sorted(CAMERA_KEYS)}."
        )
    for _name, _producer in CAMERA_KEYS.items():
        if _name not in _keep and _producer in PRODUCERS:
            _prune(_producer, f"not in RCAM_CAMERAS={_wanted}")
