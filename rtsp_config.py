# config.py

FULL_TAG = "full"
LOW_TAG = "low"

FULL_SOCKET = "/tmp/cam_full.shm"
LOW_SOCKET = "/tmp/cam_low.shm"

FULL_WIDTH = 640
FULL_HEIGHT = 480
FULL_BITRATE = 2000

LOW_WIDTH = 640
LOW_HEIGHT = 480
LOW_BITRATE = 200

SOCKETS = {
    FULL_TAG: FULL_SOCKET,
    LOW_TAG: LOW_SOCKET,
}

# any producers that need to run to set up srcs for factories go here
# ie clone video0 to shared memory sinks
# should be 1 to many (otherwise just make it a factory)
PRODUCERS = {
    "video0-fork": f"""
        v4l2src device=/dev/video0 io-mode=mmap !
        video/x-raw,format=YUY2,width={FULL_WIDTH},height={FULL_HEIGHT},framerate=30/1 !
        videoconvert !
        video/x-raw,format=NV12 !
        tee name=t

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        shmsink socket-path={FULL_SOCKET} wait-for-connection=false sync=false async=false shm-size=67108864

        t. ! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        videoscale !
        videoconvert !
        video/x-raw,format=NV12,width={LOW_WIDTH},height={LOW_HEIGHT} !
        shmsink socket-path={LOW_SOCKET} wait-for-connection=false sync=false async=false shm-size=16777216
        """,
}

# any rtsp factories go here
# these are the layer before rtsp server
# should be 1 to 1
FACTORIES = {
    FULL_TAG: f"""
        (
        shmsrc socket-path={FULL_SOCKET} is-live=true do-timestamp=true !
        video/x-raw,format=NV12,width={FULL_WIDTH},height={FULL_HEIGHT},framerate=30/1 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        vaapih264enc tune=low-power bitrate={FULL_BITRATE} keyframe-period=30 !
        h264parse config-interval=-1 !
        rtph264pay name=pay0 pt=96 config-interval=-1
        )
        """,
    LOW_TAG: f"""
        (
        shmsrc socket-path={LOW_SOCKET} is-live=true do-timestamp=true !
        video/x-raw,format=NV12,width={LOW_WIDTH},height={LOW_HEIGHT},framerate=30/1 !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        vaapih264enc tune=low-power bitrate={LOW_BITRATE} keyframe-period=30 !
        h264parse config-interval=-1 !
        rtph264pay name=pay0 pt=96 config-interval=-1
        )
        """,
}