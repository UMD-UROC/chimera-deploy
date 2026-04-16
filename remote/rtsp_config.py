# config.py

HIRES_TAG = "hires"
LOWRES_TAG = "lowres"

HIRES_SOCKET = "/tmp/hires_nv.sock"
LOWRES_SOCKET = "/tmp/lowres_nv.sock"

HIRES_WIDTH = 640
HIRES_HEIGHT = 512
HIRES_BITRATE = 1000000
HIRES_PEAK_BITRATE = 5000000

LOWRES_WIDTH = 320
LOWRES_HEIGHT = 256
LOWRES_BITRATE = 300000
LOWRES_PEAK_BITRATE = 1000000

SOCKETS = {
    HIRES_TAG: HIRES_SOCKET,
    LOWRES_TAG: LOWRES_SOCKET,
}

PRODUCERS = {
    "video1-fork": f"""
        v4l2src device=/dev/video1 io-mode=2 !
        queue max-size-buffers=1 leaky=downstream !
        video/x-raw,width={HIRES_WIDTH},height={HIRES_HEIGHT},format=I420 !
        nvvidconv !
        video/x-raw(memory:NVMM),format=NV12 !
        tee name=t

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvunixfdsink socket-path={HIRES_SOCKET} sync=false

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv !
        video/x-raw(memory:NVMM),width={LOWRES_WIDTH},height={LOWRES_HEIGHT},format=NV12 !
        nvunixfdsink socket-path={LOWRES_SOCKET} sync=false
        """,
}

FACTORIES = {
    HIRES_TAG: f"""
        (
        nvunixfdsrc socket-path={HIRES_SOCKET} !
        video/x-raw(memory:NVMM),format=NV12,width={HIRES_WIDTH},height={HIRES_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=0 bitrate={HIRES_BITRATE} peak-bitrate={HIRES_PEAK_BITRATE} iframeinterval=30 insert-sps-pps=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
    LOWRES_TAG: f"""
        (
        nvunixfdsrc socket-path={LOWRES_SOCKET} !
        video/x-raw(memory:NVMM),format=NV12,width={LOWRES_WIDTH},height={LOWRES_HEIGHT} !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=0 bitrate={LOWRES_BITRATE} peak-bitrate={LOWRES_PEAK_BITRATE} iframeinterval=30 insert-sps-pps=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay name=pay0 pt=96 config-interval=1
        )
        """,
}