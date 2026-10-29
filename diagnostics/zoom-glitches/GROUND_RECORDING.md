# Ground recording

Use `px4sim ui`: `a` starts a bag and video, `A` stops them, `b` starts only a bag, and `B` stops it.

The ground records streams for active aircraft. Each stream connects independently. A missing camera does not stop the bag or another video. The UI shows the bag size and the number of streams with current output.

Each session keeps its MCAP, metadata, videos, per-stream logs, and `recording-status.json`. A session log sits beside the bag directory. `logs/recording.log` links to the latest session log. The UI also keeps its log inside the bag directory.

The video relay shares one TCP connection per camera. Each recorder starts with a complete keyframe. It requests a 200 ms network buffer and writes without an extra userspace file buffer. A worker retries failed connections and restarts a stream after 15 seconds without file growth. Each restart uses a new numbered segment. It preserves earlier segments and removes empty files.

Humble rosbag2 0.15.17 can destroy subscriptions while discovery still reads them during shutdown. The crash dump from the October 29 test shows this race. The private transport library waits for discovery before cleanup. It also stops further subscription creation during shutdown. Topic discovery remains enabled during recording. See [upstream issue 1852](https://github.com/ros2/rosbag2/issues/1852).

The source bundle pins rosbag2 commit `bc63926c2e06efa480a957549be88b614fa96c82`, with its Apache-2.0 license. The build supports installed transport versions 0.15.16 and 0.15.17, whose class layouts match. The first recording builds a private library in `~/.cache/chimera/rosbag2`. Later recordings reuse it. The recorder alone uses this library. System ROS files stay unchanged. Other installed versions fail preparation and require an ABI review.

Shutdown allows 30 seconds for a clean stop before further signals. The supervisor checks the MCAP footer and metadata after shutdown. A bag-and-video session also requires nonempty video. An incomplete result returns an error. The status file lists each stream separately, including unavailable cameras. A saved session does not imply that every requested camera was available throughout the test.

Validation before deployment:
- 37 process and recovery tests passed.
- Two native GStreamer tests passed, including the first-keyframe gate.
- Python compilation, shell syntax, and Git whitespace checks passed.
- Three live recordings saved bags and six video streams with uas1, uas3, and uas4 connected.
- The final clip test saved 156,228 ROS messages over 48.6 seconds. It included images from all three aircraft.
- All six clips started with a keyframe. Their source timestamps increased throughout. FFmpeg decoded them without picture errors. The decode test used new output timestamps to exclude muxer warnings. Source timestamp checks used the original packets.

The inactive uas2 was excluded. Uas1 thermal returned RTSP 503 in the current day configuration. Its retries did not interrupt the six available streams.
