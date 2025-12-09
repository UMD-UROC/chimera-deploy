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
IMAGE_TOPICS = ["/uas3/target_locations", "/uas4/target_locations"]
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
    custom_msg = deserialize_message(message.data, TargetLocations)
    img_msg = custom_msg.source_img

    # Convert ROS Image to OpenCV format
    height, width = img_msg.height, img_msg.width
    encoding = img_msg.encoding.lower()
    img = np.frombuffer(img_msg.data, dtype=np.uint8).reshape(height, width, -1)

    if encoding == "rgb8":
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    elif encoding != "bgr8":
        print(f"⚠️ Unsupported encoding: {encoding}")
        continue

    # --- Split image into 6 tiles (3x2 grid) ---
    tile_w, tile_h = 640, 640
    stride_x, stride_y = 640, 540  # to cover 1080 height with 2 tiles

    tile_id = 0
    
    
    tile = img

    # Run YOLO on the tile
    results = model.predict(tile, classes=[0])
    annotated = results[0].plot()

    # Save each annotated tile
    out_name = f"frame_{message.log_time}_tile_{tile_id}.jpg"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    cv2.imwrite(out_path, annotated)
    print(f"Saved: {out_path}")
    tile_id += 1
    
    for y in range(0, height, stride_y):
        for x in range(0, width, stride_x):
            tile = img[y:y+tile_h, x:x+tile_w]

            # Pad to 640x640 if needed (bottom/right edges)
            pad_y = max(0, tile_h - tile.shape[0])
            pad_x = max(0, tile_w - tile.shape[1])
            if pad_x > 0 or pad_y > 0:
                tile = cv2.copyMakeBorder(tile, 0, pad_y, 0, pad_x, cv2.BORDER_CONSTANT, value=(0,0,0))

            # Run YOLO on the tile
            results = model.predict(tile, classes=[0])
            annotated = results[0].plot()

            # Save each annotated tile
            out_name = f"frame_{message.log_time}_tile_{tile_id}.jpg"
            out_path = os.path.join(OUTPUT_DIR, out_name)
            cv2.imwrite(out_path, annotated)
            print(f"Saved: {out_path}")
            tile_id += 1

f.close()
print(f"\n✅ Annotated tiles saved in: {OUTPUT_DIR}")

