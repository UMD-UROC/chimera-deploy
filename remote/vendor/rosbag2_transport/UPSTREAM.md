Source: ros2/rosbag2 0.15.17, commit bc63926c2e06efa480a957549be88b614fa96c82.
License: Apache-2.0. The upstream headers, sources, and build files are included.

Local changes in recorder.cpp:
- Wait for discovery before subscription and writer cleanup.
- Stop subscription creation when shutdown starts.

The private build supports Humble 0.15.16 and 0.15.17. Their transport class layouts match. System ROS files remain unchanged.
