# klv_config.py

from dataclasses import dataclass

from klv_projection import Attitude

SOURCE_RTSP_HOST = "127.0.0.1"
SOURCE_RTSP_PORT = 8554
ATAK_RTSP_PORT = 8555
GROUND_STATION_IP = "10.200.142.60"

KLV_RATE_HZ = 10.0
TELEMETRY_TIMEOUT_S = 2.0
MAVLINK_RECONNECT_DELAY_S = 2.0

BORESIGHT_ALIGNED_WITH_GIMBAL = Attitude(yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0)


@dataclass(frozen=True)
class Camera:
    horizontal_fov_deg: float
    vertical_fov_deg: float
    boresight_offset: Attitude = BORESIGHT_ALIGNED_WITH_GIMBAL


# Footprint accuracy is bounded by these; take them from the lens datasheet or a ground calibration.
RGB_CAMERA = Camera(horizontal_fov_deg=66.0, vertical_fov_deg=41.0)
BOSON_640_THERMAL_18MM = Camera(horizontal_fov_deg=32.0, vertical_fov_deg=26.0)


@dataclass(frozen=True)
class Stream:
    atak_mount: str
    source_mount: str
    mavlink_endpoint: str
    camera: Camera


STREAMS = (
    Stream("uas3/rgb", "rgbl3", "udpin:127.0.0.1:14403", RGB_CAMERA),
    Stream("uas3/thermal", "thermall3", "udpin:127.0.0.1:14403", BOSON_640_THERMAL_18MM),
    Stream("uas4/rgb", "rgbl4", "udpin:127.0.0.1:14404", RGB_CAMERA),
    Stream("uas4/thermal", "thermall4", "udpin:127.0.0.1:14404", BOSON_640_THERMAL_18MM),
)
