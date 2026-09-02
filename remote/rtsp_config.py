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
RGB_WIDTH = 1920
RGB_HEIGHT = 1080
RGB_FRAMERATE = "30/1"
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
        video/x-raw,width={THERMAL_WIDTH},height={THERMAL_HEIGHT},format=I420 !
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

# Drop the pipelines that reference a camera that is not attached. SOCKETS is
# left whole so the server still clears stale socket files for those streams.
MISSING_CAMERAS = []

if RGB_DEVICE is None:
    MISSING_CAMERAS.append("C1 PRO")
    del PRODUCERS["rgb-fork"]
    del FACTORIES[RGB], FACTORIES[RGB_LOWRES]

if THERMAL_DEVICE is None:
    MISSING_CAMERAS.append("Boson")
    del PRODUCERS["thermal-fork"]
    del FACTORIES[THERMAL], FACTORIES[THERMAL_LOWRES]
