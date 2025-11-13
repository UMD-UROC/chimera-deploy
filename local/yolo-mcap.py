import os
import cv2
import numpy as np
from ultralytics import YOLO
from mcap.reader import make_reader
from mcap_ros2.decoder import Decoder as ROS2Decoder
from rosidl_runtime_py.utilities import get_message
from rclpy.serialization import deserialize_message

# --- Configuration ---
MCAP_PATH = "/home/ctitus/ros2_ws/bags/2025-09-28-dtc-day-c130/uav-2025_09_28-15_14_44.mcap"
OUTPUT_DIR = "annotated_frames"
IMAGE_TOPICS = ["/uas3/target_locations", "/uas4/target_locations"]  # your custom msg topic
MODEL_PATH = "yolov8x.pt"

os.makedirs(OUTPUT_DIR, exist_ok=True)
model = YOLO(MODEL_PATH)

# --- Setup ---
f = open(MCAP_PATH, "rb")
reader = make_reader(f)
decoder = ROS2Decoder()

# import your custom message definition dynamically
TargetLocations = get_message("cdcl_umd_msgs/msg/TargetBoxArray")
ImageMsg = get_message("sensor_msgs/msg/Image")

for schema, channel, message in reader.iter_messages(topics=IMAGE_TOPICS):
    # Decode custom message
    custom_msg = deserialize_message(message.data, TargetLocations)

    # Extract embedded image (sensor_msgs/Image)
    img_msg = custom_msg.source_img

    # Convert ROS Image to OpenCV format
    height, width = img_msg.height, img_msg.width
    encoding = img_msg.encoding.lower()
    img = np.frombuffer(img_msg.data, dtype=np.uint8).reshape(height, width, -1)

    if encoding == "rgb8":
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    elif encoding == "bgr8":
        pass
    else:
        print(f"Unsupported encoding: {encoding}")
        continue

    # YOLO inference
    results = model.predict(img, classes=[0])
    #results = model.predict(img, classes=[0], conf=0.6)
    annotated = results[0].plot()

    out_path = os.path.join(OUTPUT_DIR, f"frame_{message.log_time}.jpg")
    cv2.imwrite(out_path, annotated)
    print(f"Saved: {out_path}")

f.close()
print(f"Annotated frames saved in: {OUTPUT_DIR}")

