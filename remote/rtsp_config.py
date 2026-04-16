# config.py

HIRES_TAG = "hires"
LOWRES_TAG = "lowres"

HIRES_SOCKET = "/tmp/cam_hires.shm"
LOWRES_SOCKET = "/tmp/cam_lowres.shm"

HIRES_WIDTH = 640
HIRES_HEIGHT = 480
HIRES_BITRATE = 2000

LOWRES_WIDTH = 640
LOWRES_HEIGHT = 480
LOWRES_BITRATE = 200

SOCKETS = {
    HIRES_TAG: HIRES_SOCKET,
    LOWRES_TAG: LOWRES_SOCKET,
}

# any producers that need to run to set up srcs for factories go here
# ie clone video0 to shared memory sinks
# should be 1 to many (otherwise just make it a factory)
# PRODUCERS = {
#     "video0-fork": f"""
#         v4l2src device=/dev/video0 io-mode=mmap do-timestamp=true !
#         video/x-raw,format=YUY2,width={HIRES_WIDTH},height={HIRES_HEIGHT},framerate=30/1 !
#         videoconvert !
#         video/x-raw,format=NV12 !
#         tee name=t

#         t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
#         shmsink socket-path={HIRES_SOCKET} wait-for-connection=false sync=false async=false shm-size=67108864

#         t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
#         videoscale !
#         videoconvert !
#         video/x-raw,format=NV12,width={LOWRES_WIDTH},height={LOWRES_HEIGHT} !
#         shmsink socket-path={LOWRES_SOCKET} wait-for-connection=false sync=false async=false shm-size=16777216
#         """,
# }
PRODUCERS = {
    "video0-fork": f"""
        nvarguscamerasrc sensor-id=0 wbmode=1 !
        queue max-size-buffers=1 leaky=downstream !
        video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1 !
        nvvidconv flip-method=2 !
        video/x-raw(memory:NVMM) !
        tee name=t

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc control-rate=0 bitrate={HIRES_BITRATE} peak-bitrate=5000000 iframeinterval=0 insert-sps-pps=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay config-interval=1 pt=96 !
        shmsink socket-path={HIRES_SOCKET} wait-for-connection=false sync=false async=false shm-size=67108864

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv !
        video/x-raw(memory:NVMM),width={LOWRES_WIDTH},height={LOWRES_HEIGHT},format=NV12 !
        nvv4l2h265enc control-rate=0 bitrate={LOWRES_BITRATE} peak-bitrate=5000000 iframeinterval=0 insert-sps-pps=true EnableTwopassCBR=false !
        h265parse !
        rtph265pay config-interval=1 pt=96 !
        shmsink socket-path={LOWRES_SOCKET} wait-for-connection=false sync=false async=false shm-size=16777216
        """,
}

# any rtsp factories go here
# these are the layer before rtsp server
# should be 1 to 1
FACTORIES = {
    HIRES_TAG: f"""
        (
        shmsrc socket-path={HIRES_SOCKET} is-live=true do-timestamp=true !
        application/x-rtp,media=video,encoding-name=H265,payload=96,clock-rate=90000 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        rtph265depay !
        h265parse config-interval=-1 !
        rtph265pay name=pay0 pt=96 config-interval=-1
        )
        """,
    LOWRES_TAG: f"""
        (
        shmsrc socket-path={LOWRES_SOCKET} is-live=true do-timestamp=true !
        application/x-rtp,media=video,encoding-name=H265,payload=96,clock-rate=90000 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        rtph265depay !
        h265parse config-interval=-1 !
        rtph265pay name=pay0 pt=96 config-interval=-1
        )
        """,
}