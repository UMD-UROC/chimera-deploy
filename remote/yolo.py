import cv2
from ultralytics import YOLO

# Load pretrained YOLOv11 model (nano version for speed)
model = YOLO("yolo11n.pt")

# RTSP stream
rtsp_url = "rtsp://127.0.0.1:8554/rgb"
cap = cv2.VideoCapture(rtsp_url)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Run YOLO inference
    results = model(frame, verbose=False)
    annotated = results[0].plot()  # Draw boxes + labels

    # Display
    cv2.imshow("YOLOv11 RTSP", annotated)
    if cv2.waitKey(1) & 0xFF == 27:  # ESC to quit
        break

cap.release()
cv2.destroyAllWindows()

