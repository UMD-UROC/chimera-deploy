#!/usr/bin/env python3
"""Read recorded image arrivals and heartbeat rates from an MCAP stream."""
import json
import sys
import cv2
import numpy as np
from mcap.reader import NonSeekingReader
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

images = []
rates = []
status_count = 0
decoded_samples = 0
decode_failures = 0
for schema, channel, message in NonSeekingReader(sys.stdin.buffer).iter_messages(
        topics=['/uas1/image', '/uas1/deepstream/heartbeat', '/ds/status'],
        log_time_order=False):
    if channel.topic == '/uas1/image':
        images.append(message.log_time / 1e9)
        if len(images) % 150 == 1:
            value = deserialize_message(message.data, get_message(schema.name))
            decoded = cv2.imdecode(np.frombuffer(value.data, dtype=np.uint8), cv2.IMREAD_COLOR)
            decoded_samples += 1
            decode_failures += int(decoded is None)
    elif channel.topic == '/uas1/deepstream/heartbeat':
        value = deserialize_message(message.data, get_message(schema.name))
        rates.append((message.log_time / 1e9, value.image_rate_hz))
    else:
        status_count += 1
images.sort()
pairs = list(zip(images, images[1:]))
print(json.dumps(dict(
    images=len(images),
    image_span_seconds=images[-1]-images[0] if images else None,
    max_image_gap_seconds=max((b-a for a,b in pairs), default=None),
    image_gaps_over_half_second=[dict(unix_time=a, gap_seconds=b-a)
                                for a,b in pairs if b-a > 0.5],
    heartbeat_count=len(rates),
    minimum_heartbeat_rate=min((r for _,r in rates), default=None),
    zero_rate_heartbeats=[t for t,r in rates if r==0],
    status_count=status_count, decoded_samples=decoded_samples,
    sampled_jpeg_decode_failures=decode_failures), indent=2))
