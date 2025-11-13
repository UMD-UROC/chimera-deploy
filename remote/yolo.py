import gi, cv2
from ultralytics import YOLO
gi.require_version('Gst', '1.0')
from gi.repository import Gst

Gst.init(None)

# RTSP input
cap = cv2.VideoCapture("rtsp://127.0.0.1:8554/rgb")
model = YOLO("yolo11n.pt")
model.to("cuda")

# Create pipeline that feeds frames into existing RTSP server's appsrc
pipeline = Gst.parse_launch(
    "appsrc name=annotated_src is-live=true format=3 ! "
    "videoconvert ! x264enc tune=zerolatency bitrate=2000 speed-preset=ultrafast ! "
    "rtph264pay config-interval=1 pt=96 ! "
    "udpsink host=127.0.0.1 port=5000"
)
appsrc = pipeline.get_by_name("annotated_src")
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

