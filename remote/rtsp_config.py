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
# 720x576, not 1080p, because 1080p takes the Boson off the USB bus.
#
# Both USB cameras sit on one hub and share one high speed bus. The C1 PRO is
# isochronous, so it reserves its bandwidth before anything else runs. The
# Boson is bulk, so it reserves nothing and lives on what is left. The mode
# picked here decides the C1 PRO alternate setting, and that decides whether
# the thermal camera keeps running. Measured on d1, 2026-09-08:
#
#   C1 PRO mode   alt   reserved     Boson beside it
#   1920x1080     5     19.2 MB/s    died at 83 s
#   1280x1024     ?     not measured not measured
#   1280x720      4     12.8 MB/s    not measured
#   720x576       3     6.4 MB/s     survived 150 s, no error
#   640x480       3     6.4 MB/s     survived 120 s, no error
#
# The Boson wants 29.5 MB/s of the roughly 40 the bus carries, and it cannot be
# made to want less. 60 fps is all it really sends whatever the caps ask for,
# so the only lever left is this one. 720x576 and 640x480 cost the same
# reservation, so take the larger picture.
#
# Raise this only with the thermal camera watched. 1280x720 is the next rung
# and it is untested.
RGB_WIDTH = int(os.environ.get("RGB_WIDTH", 720))
RGB_HEIGHT = int(os.environ.get("RGB_HEIGHT", 576))
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

# Empty, which takes the camera default of 60. 30 was tried here as a fix and
# measured as no fix at all, on d1, 2026-09-08:
#
#   thermal alone, 60 fps          survived 90 s, no error
#   thermal + C1 PRO, 60 fps       died at 83 s
#   thermal + C1 PRO, at 30 fps    died at 68 s
#
# The Boson took the setting: v4l2-ctl reported 30.000 fps on the node. Its URB
# rate did not move, about 2000/s in both runs, so the camera very likely keeps
# sending 60 Hz on the wire and the frames get dropped above the driver. Do not
# reach for this knob again to buy USB bandwidth without measuring the wire
# first.
THERMAL_FRAMERATE = os.environ.get("THERMAL_FRAMERATE", "")

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
        video/x-h264,width={RGB_WIDTH},height={RGB_HEIGHT} !
        h264parse !
        video/x-h264,stream-format=byte-stream,alignment=au !
        nvv4l2decoder enable-max-performance=1 !
        """
else:
    RGB_DECODE = f"""
        image/jpeg,width={RGB_WIDTH},height={RGB_HEIGHT} !
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
