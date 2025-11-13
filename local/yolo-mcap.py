import os
import cv2
import numpy as np
from ultralytics import YOLO
from mcap.reader import make_reader
from mcap_ros2.decoder import Decoder as ROS2Decoder
from io import BytesIO

# --- Configuration ---
MCAP_PATH = "/home/ctitus/ros2_ws/bags/medic-quick-trimmed/medic-quick-trimmed.mcap"
OUTPUT_DIR = "annotated_frames"
IMAGE_TOPIC = "/uas3/target_locations"  # Change to your actual topic
MODEL_PATH = "yolov8n.pt"          # Or your custom model path

os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Load YOLOv8 model ---
model = YOLO(MODEL_PATH)

# --- Read MCAP ---
f = open(MCAP_PATH, "rb")  # keep file open
reader = make_reader(f)
decoder = ROS2Decoder()

topics = set()
for schema, channel, message in reader.iter_messages():
    topics.add(channel.topic)
print("\n".join(sorted(topics)))


for schema, channel, message in reader.iter_messages(topics=[IMAGE_TOPIC]):
    print("image")
    ros_msg = decoder.decode(channel.schema, message.data)

    height, width = ros_msg.height, ros_msg.width
    encoding = ros_msg.encoding.lower()
    img = np.frombuffer(ros_msg.data, dtype=np.uint8).reshape(height, width, -1)

    if encoding == "rgb8":
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    results = model(img)
    annotated = results[0].plot()

    out_path = os.path.join(OUTPUT_DIR, f"frame_{message.log_time}.jpg")
    cv2.imwrite(out_path, annotated)
    print(f"Saved: {out_path}")

f.close()
print(f"\n✅ Annotated frames saved in: {OUTPUT_DIR}")


