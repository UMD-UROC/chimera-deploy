import gi, cv2
from ultralytics import YOLO
gi.require_version('Gst', '1.0')
from gi.repository import Gst

Gst.init(None)

# YOLO + input stream
model = YOLO("yolo11n.pt").to("cuda")
cap = cv2.VideoCapture("rtsp://127.0.0.1:8554/rgb")

# Build pipeline that matches the appsrc mount on the RTSP server
pipeline_str = (
    "appsrc name=rgb_annotated is-live=true format=3 ! "
    "video/x-raw,format=BGR,width=640,height=480,framerate=30/1 ! "
    "videoconvert ! "
    "nvvidconv ! "
    "queue max-size-buffers=1 leaky=downstream ! "
    "video/x-raw(memory:NVMM),format=NV12 ! "
    "nvv4l2h265enc control-rate=0 bitrate=1000000 peak-bitrate=5000000 "
    "iframeinterval=0 insert-sps-pps=true EnableTwopassCBR=false ! "
    "h265parse ! rtph265pay config-interval=1 pt=96 name=pay0"
)

pipeline = Gst.parse_launch(pipeline_str)
appsrc = pipeline.get_by_name("rgb_annotated")
pipeline.set_state(Gst.State.PLAYING)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Run YOLO detection
    results = model(frame, verbose=False)
    annotated = results[0].plot()

    # Convert frame to GstBuffer and push
    data = annotated.tobytes()
    buf = Gst.Buffer.new_allocate(None, len(data), None)
    buf.fill(0, data)
    buf.pts = buf.dts = int(Gst.util_uint64_scale(
        cap.get(cv2.CAP_PROP_POS_MSEC), Gst.SECOND, 1000))
    buf.duration = Gst.SECOND // 30
    appsrc.emit("push-buffer", buf)

cap.release()
appsrc.emit("end-of-stream")
pipeline.set_state(Gst.State.NULL)

