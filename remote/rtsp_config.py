# config.py

RGB_WIDTH = 3840
RGB_HEIGHT = 2160
RGB_FRAMERATE = "30/1"
RGB_BITRATE = 1000000
RGB_PEAK_BITRATE = 5000000

RGB_LOWRES_WIDTH = 640
RGB_LOWRES_HEIGHT = 360
RGB_LOWRES_BITRATE = 10000
RGB_LOWRES_PEAK_BITRATE = 50000

THERMAL_WIDTH = 640
THERMAL_HEIGHT = 512
THERMAL_BITRATE = 1000000
THERMAL_PEAK_BITRATE = 5000000

THERMAL_LOWRES_WIDTH = 320
THERMAL_LOWRES_HEIGHT = 256
THERMAL_LOWRES_BITRATE = 10000
THERMAL_LOWRES_PEAK_BITRATE = 50000

RGB = "rgb"
RGB_LOWRES = "rgb-lowres"
THERMAL = "thermal"
THERMAL_LOWRES = "thermal-lowres"

def SOCKET(tag):
    return f"/tmp/{tag}_nv.sock"

SOCKETS = {
    RGB: SOCKET(RGB),
    RGB_LOWRES: SOCKET(RGB_LOWRES),
    THERMAL: SOCKET(THERMAL),
    THERMAL_LOWRES: SOCKET(THERMAL_LOWRES),
}

PRODUCERS = {
    "rgb-fork": f"""
        nvarguscamerasrc sensor-id=0 wbmode=1 do-timestamp=true !
        video/x-raw(memory:NVMM),width={RGB_WIDTH},height={RGB_HEIGHT},framerate={RGB_FRAMERATE} !
        nvvidconv flip-method=2 interpolation-method=1 !
        video/x-raw(memory:NVMM),format=NV12 !
        tee name=t

        t. ! queue leaky=downstream max-size-buffers=1 !
        nvunixfdsink socket-path={SOCKETS[RGB]} sync=false

        t. ! queue leaky=downstream max-size-buffers=1 !
        nvvidconv interpolation-method=1 !
        video/x-raw(memory:NVMM),width={RGB_LOWRES_WIDTH},height={RGB_LOWRES_HEIGHT},format=NV12 !
        nvunixfdsink socket-path={SOCKETS[RGB_LOWRES]} sync=false
        """,
    # "thermal-fork": f"""
    #     v4l2src device=/dev/video1 io-mode=2 do-timestamp=true !
    #     queue max-size-buffers=1 leaky=downstream !
    #     video/x-raw,width={THERMAL_WIDTH},height={THERMAL_HEIGHT},format=I420 !
    #     nvvidconv !
    #     video/x-raw(memory:NVMM),format=NV12 !
    #     tee name=t

    #     t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
    #     nvunixfdsink socket-path={SOCKETS[THERMAL]} sync=false

    #     t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
    #     nvvidconv !
    #     video/x-raw(memory:NVMM),width={THERMAL_LOWRES_WIDTH},height={THERMAL_LOWRES_HEIGHT},format=NV12 !
    #     nvunixfdsink socket-path={SOCKETS[THERMAL_LOWRES]} sync=false
    #     """,
}

FACTORIES = {
    RGB: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[RGB]} num-extra-surfaces=4 !
        video/x-raw(memory:NVMM),format=NV12,width={RGB_WIDTH},height={RGB_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 !
        nvv4l2h265enc maxperf-enable=1 preset-level=1 control-rate=1 bitrate={RGB_BITRATE} peak-bitrate={RGB_PEAK_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false zerolatency=true !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
    RGB_LOWRES: f"""
        (
        nvunixfdsrc socket-path={SOCKETS[RGB_LOWRES]} num-extra-surfaces=4 !
        video/x-raw(memory:NVMM),format=NV12,width={RGB_LOWRES_WIDTH},height={RGB_LOWRES_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 !
        nvv4l2h265enc maxperf-enable=1 preset-level=1 control-rate=1 bitrate={RGB_LOWRES_BITRATE} peak-bitrate={RGB_LOWRES_PEAK_BITRATE} iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false zerolatency=true !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
    # THERMAL: f"""
    #     (
    #     nvunixfdsrc socket-path={SOCKETS[THERMAL]} !
    #     video/x-raw(memory:NVMM),format=NV12,width={THERMAL_WIDTH},height={THERMAL_HEIGHT} !
    #     queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
    #     nvv4l2h265enc maxperf-enable=1 control-rate=0 bitrate={THERMAL_BITRATE} peak-bitrate={THERMAL_PEAK_BITRATE} iframeinterval=30 insert-sps-pps=true EnableTwopassCBR=false !
    #     h265parse !
    #     rtph265pay name=pay0 pt=96 config-interval=1
    #     )
    #     """,
    # THERMAL_LOWRES: f"""
    #     (
    #     nvunixfdsrc socket-path={SOCKETS[THERMAL_LOWRES]} !
    #     video/x-raw(memory:NVMM),format=NV12,width={THERMAL_LOWRES_WIDTH},height={THERMAL_LOWRES_HEIGHT} !
    #     queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
    #     nvv4l2h265enc maxperf-enable=1 control-rate=0 bitrate={THERMAL_LOWRES_BITRATE} peak-bitrate={THERMAL_LOWRES_PEAK_BITRATE} iframeinterval=30 insert-sps-pps=true EnableTwopassCBR=false !
    #     h265parse !
    #     rtph265pay name=pay0 pt=96 config-interval=1
    #     )
    #     """,
}