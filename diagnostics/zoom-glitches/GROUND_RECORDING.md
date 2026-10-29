# Native recording and restart

Use `px4sim ui`: `a` starts a bag and video, `A` stops them, `b` starts only a bag, and `B` stops it.

Recording uses the existing session log. It creates no recording status files or per-stream logs. Each video recorder runs independently. A missing stream does not stop the bag or other cameras. Video uses the normal GStreamer recording pipeline, without retries or keyframe filtering.

The private Humble transport library retains the fix for the rosbag discovery shutdown race. Restart prepares this library while the ROS stack is stopped. Recording uses the prepared library and never compiles it. The first restart on a machine can take longer while it builds the library. System ROS files stay unchanged.

Restart closes the native recording, stops the local ROS CLI daemon, and removes the stack containers before DDS cleanup. Cleanup removes stale shared-memory data, lock files, and semaphores without an age delay. A live lock or a removal failure stops the restart instead of reporting success. Objects with live owners remain intact. The stack starts only after cleanup and preparation succeed.

The earlier acceptance JSON records tests of the previous recording implementation. Current changes remove its extra status and logging machinery.
