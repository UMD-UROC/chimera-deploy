import cv2
from ultralytics import YOLO

model = YOLO("yolov8n.pt")
rtsp = "rtspsrc location=rtsp://127.0.0.1:8554/rgb latency=100 ! \
        rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! \
        video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! appsink"

cap = cv2.VideoCapture(rtsp, cv2.CAP_GSTREAMER)
if not cap.isOpened():
    exit("Failed to open stream")

while True:
    ret, frame = cap.read()
    if not ret:
        break
    results = model(frame)
    cv2.imshow("YOLO", results[0].plot())
    if cv2.waitKey(1) == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

