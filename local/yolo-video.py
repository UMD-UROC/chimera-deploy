from ultralytics import YOLO

# Load a pretrained YOLOv8 model (you can replace with your own .pt file)
model = YOLO("yolov8n.pt")

# Input and output video paths
input_video = "input.mp4"
output_video = "output_annotated.mp4"

# Run YOLOv8 inference on the video
results = model.predict(
    source=input_video,    # path to input video
    save=True,             # save annotated video automatically
    project="runs/detect", # output directory
    name="video_result",   # subfolder name
    exist_ok=True          # overwrite existing
)

# After running, the annotated video will be saved under:
# runs/detect/video_result/input.mp4
print("Annotated video saved in:", results[0].save_dir)

