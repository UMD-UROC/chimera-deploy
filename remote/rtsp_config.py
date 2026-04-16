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
PRODUCERS = {
    "video0-fork": f"""
        v4l2src device=/dev/video0 io-mode=mmap do-timestamp=true !
        video/x-raw,format=YUY2,width={HIRES_WIDTH},height={HIRES_HEIGHT},framerate=30/1 !
        videoconvert !
        video/x-raw,format=NV12 !
        tee name=t

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        shmsink socket-path={HIRES_SOCKET} wait-for-connection=false sync=false async=false shm-size=67108864

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        videoscale !
        videoconvert !
        video/x-raw,format=NV12,width={LOWRES_WIDTH},height={LOWRES_HEIGHT} !
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
        video/x-raw,format=NV12,width={HIRES_WIDTH},height={HIRES_HEIGHT},framerate=30/1 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        vaapih265enc tune=low-power bitrate={HIRES_BITRATE} keyframe-period=30 !
        h265parse config-interval=-1 !
        rtph265pay name=pay0 pt=96 config-interval=-1
        )
        """,
    LOWRES_TAG: f"""
        (
        shmsrc socket-path={LOWRES_SOCKET} is-live=true do-timestamp=true !
        video/x-raw,format=NV12,width={LOWRES_WIDTH},height={LOWRES_HEIGHT},framerate=30/1 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        vaapih265enc tune=low-power bitrate={LOWRES_BITRATE} keyframe-period=30 !
        h265parse config-interval=-1 !
        rtph265pay name=pay0 pt=96 config-interval=-1
        )
        """,
}