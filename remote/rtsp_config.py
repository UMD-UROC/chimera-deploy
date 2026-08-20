# config.py

RGB_WIDTH = 3840
RGB_HEIGHT = 2160
RGB_FRAMERATE = "30/1"
# RGB_WIDTH = 1920
# RGB_HEIGHT = 1080
# RGB_FRAMERATE = "60/1"
RGB_BITRATE = 200000000 # nv recording bitrate set in record_nv_streams.sh

RGB_LOWRES_WIDTH = 640
RGB_LOWRES_HEIGHT = 360
RGB_LOWRES_BITRATE = 1000000

THERMAL_WIDTH = 640
THERMAL_HEIGHT = 512
THERMAL_BITRATE = 8000000 # nv recording bitrate set in record_nv_streams.sh

# THERMAL_LOWRES_WIDTH = 640
# THERMAL_LOWRES_HEIGHT = 512
THERMAL_LOWRES_WIDTH = THERMAL_WIDTH
THERMAL_LOWRES_HEIGHT = THERMAL_HEIGHT
THERMAL_LOWRES_BITRATE = 400000

RGB = "rgb"
RGB_DEEPSTREAM = "rgbds"
RGB_LOWRES = "rgbl"
RGB_LOWRES_KLV = "rgblk"
THERMAL = "thermal"
THERMAL_DEEPSTREAM = "thermalds"
THERMAL_LOWRES = "thermall"
THERMAL_RAW = "thermalraw"

def SOCKET(tag):
    return f"/tmp/{tag}_nv.sock"

SOCKETS = {
    RGB: SOCKET(RGB),
    RGB_DEEPSTREAM: SOCKET(RGB_DEEPSTREAM),
    RGB_LOWRES: SOCKET(RGB_LOWRES),
    RGB_LOWRES_KLV: SOCKET(RGB_LOWRES_KLV),
    THERMAL: SOCKET(THERMAL),
    THERMAL_DEEPSTREAM: SOCKET(THERMAL_DEEPSTREAM),
    THERMAL_LOWRES: SOCKET(THERMAL_LOWRES),
    THERMAL_RAW: SOCKET(THERMAL_RAW),
}

PRODUCERS = {
    "rgb-fork": f"""
        nvarguscamerasrc sensor-id=0 wbmode=1 do-timestamp=true !
        video/x-raw(memory:NVMM),width={RGB_WIDTH},height={RGB_HEIGHT},framerate={RGB_FRAMERATE} !
        nvvidconv flip-method=2 interpolation-method=1 !
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
        nvunixfdsink socket-path={SOCKETS[RGB_LOWRES_KLV]} sync=false async=false
        """,
    "thermal-fork": f"""
        v4l2src device=/dev/video1 io-mode=2 do-timestamp=true !
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

KLV_APPSRC_NAME = "klv"
KLV_MUXER_NAME = "klvmux"
KLV_DELAY_QUEUE_NAME = "klvdelay"
KLV_LOCALIZATION_DELAY_NS = 500_000_000
KLV_TABLE_INTERVAL_TICKS = 45000
KLV_FRAME_INTERVAL = 1

FACTORIES = {
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
    RGB_LOWRES_KLV: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[RGB_LOWRES_KLV]} num-extra-surfaces=4 do-timestamp=true !
        video/x-raw(memory:NVMM),format=NV12,width={RGB_LOWRES_WIDTH},height={RGB_LOWRES_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate={RGB_LOWRES_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse config-interval=1 !
        video/x-h265,stream-format=byte-stream,alignment=au !
        queue name={KLV_DELAY_QUEUE_NAME} max-size-buffers=0 max-size-bytes=0 max-size-time=0 min-threshold-time={KLV_LOCALIZATION_DELAY_NS} !
        mpegtsmux name={KLV_MUXER_NAME} alignment=7 pat-interval={KLV_TABLE_INTERVAL_TICKS} pmt-interval={KLV_TABLE_INTERVAL_TICKS} si-interval={KLV_TABLE_INTERVAL_TICKS} !
        rtpmp2tpay name=pay0 pt=33

        appsrc name={KLV_APPSRC_NAME} is-live=true format=time caps="meta/x-klv,parsed=true" !
        {KLV_MUXER_NAME}.
        )
        """,
}

KLV_GEOLOCATION_ADDRESSES = {
    RGB_LOWRES_KLV: ("127.0.0.1", 15010),
}
