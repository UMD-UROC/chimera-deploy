# Reproduction and CPU profile

## Result

The long RGB outages come from decoder surface starvation under shared consumers.
Increasing `nvv4l2decoder num-extra-surfaces` from its default 1 to 32 prevents the measured long stalls.
Restoring 1 brings the stall back. This test supports a software pipeline cause for the long outages.
The exact consumer that retains the limiting surface remains unknown.
These tests do not establish the cause of every reported damaged pixel.

## Operator workflow

The tests used the existing Bash `sync` alias, which runs `chimera-deploy/sync_ui.py`.
The initial sync rebuilt and restarted the ground and uas1 stacks successfully.
Other drones were offline.
On uas1, an SSH terminal ran `~/px4-sim-stack/px4sim ui`.
The UI keys `a` and `A` started and stopped ROS bag plus video recording.
No direct recorder launch replaced that path.

The first UI recording, `rosbag2_2026_10_29-14_42_13-air-d1`, reproduced a 7.9622-second RGB gap.
The original source and its one-surface decoder setting were still active.

Stage counters were added locally, committed, pushed, and delivered through the sync alias.
The sync path does not reload native rcam when it restarts the container stack.
Systemd refused a direct service restart without authentication.
The user-owned camera process received SIGTERM, and its existing `Restart=always` policy loaded the new code.
This was an additional diagnostic lifecycle action, outside the front-door recording workflow.
No remote source edits were made.

One sync attempt failed because a new local 5g_drone branch did not yet exist remotely.
Publishing that branch allowed the next sync to complete.
The branch contains no 5g_drone code changes.

## Controlled decoder comparison

The diagnostics count buffers at capture, parser output, decoder output, raw tee, and each raw socket sink.
They also count corrupt/discontinuity flags and queue overruns.
The counters observe buffer flow without dropping buffers or changing timestamps.

| Decoder setting | Observation |
| --- | --- |
| Extra surfaces = 1 | Decoded output froze at 58 frames. Capture/parser froze at 72 buffers. |
| Extra surfaces = 1, next restart | Decoded output froze at 15 frames. Capture/parser froze at 29 buffers. |
| Extra surfaces = 32 | 1,653 decoded frames over 56 seconds, maximum decoded gap 0.140 s. |
| Extra surfaces = 32, UI recording | 2,593 decoded frames over about 88 seconds, maximum decoded gap 0.141 s. |
| Restored extra surfaces = 1 | Decoded output froze at 419 frames, around 15 seconds after startup. Capture/parser stopped at 432. |

During a freeze, decoding stops before capture and parsing.
The decoder accepts another 13–14 compressed buffers before upstream flow stops.
The raw branches stop together. This explains the matching ROS image and recording outages.
No CORRUPTED flags accompanied these measured freezes.
The watchdog eventually restarts the camera service if the freeze exceeds 15 seconds.

The successful UI recording is `rosbag2_2026_10_29-14_46_42-air-d1`.
Its RGB file contains 2,279 video packets over 81.970022 seconds.
It has no presentation timestamp gap over 0.5 seconds.
The full file was copied before this measurement.
The final branch restores 32 extra surfaces.

This changes the supply of decoder surfaces, not camera settings or CPU scheduling.
The comparison identifies surface pressure as the cause of the reproduced long stalls.
It does not prove a memory leak, hardware failure, or a specific plugin ownership defect.
Longer endurance tests and consumer retention measurements remain useful.

Short gaps remain. Capture and decode show roughly 132–141 ms pauses with bursts afterward.
The one-buffer raw queues discard frames during these bursts.
In one 88-second sample, the decoder delivered 2,593 frames and the full RGB sink received 2,446.
Thus 147 frames did not reach that sink, even though the long decode stalls stopped.
Changing that behavior requires a separate latency versus completeness decision.

## CPU profile

`profile_proc.py` samples per-thread CPU ticks through procfs over ten seconds.
One full CPU core is 100 percent. The drone has eight cores.
These are sampled process costs, not function stack profiles.
Short samples vary with recording, discovery, UI probing, and background work.

| Process or group | CPU percent during the stable recording sample |
| --- | ---: |
| ROS bag recorder | 62.95 |
| Native camera server | 42.06 |
| Pilot video recorder | 28.45 |
| MAVROS | 21.74 |
| MAVInsight total | 126.93 |
| MAVInsight gimbal | 21.74 |
| MAVInsight vehicle | 15.22 |
| MAVInsight location display | 16.92 |
| MAVInsight scoring display | 13.61 |
| MAVInsight buildings display | 12.85 |
| MAVInsight terrain display | 12.85 |
| MAVInsight footprint display | 12.00 |

Total sampled CPU use was 639.26 percent, including kernel threads.
The earlier overloaded recording sample put the bag recorder near 92 percent and several visualization processes above these values.
Background update-manager and Docker build activity also appeared during separate samples.
A sample taken during a rebuild was excluded from the stable-recording comparison.

The five display nodes together cost 68.23 percent in the baseline sample.
A ten-second diagnostic pause used SIGSTOP on only these processes, then resumed them with SIGCONT.
All five measured zero CPU during that pause.
MAVInsight total decreased to 94.31 percent, and total CPU decreased to 627.59 percent.
Other work increased, so this was not a controlled estimate of total savings.
The saved JSON includes per-process commands and thread costs for both samples.

These five display nodes are candidates for an optional aircraft visualization switch.
They draw data and do not own the vehicle or gimbal frame transforms.
Disabling them removes those aircraft-side displays and their health heartbeats.
The launch diagnostic list must change with the enabled node list.

Keep MAVInsight vehicle, gimbal, and sensor frame publishers unless their TF responsibilities move elsewhere.
They supply frames that localization and camera pointing use.
Disabling all MAVInsight would remove required transforms.
No permanent node disable was applied during this diagnosis.

## Checks and evidence

Camera selection tests: 9 passed. Existing camera watchdog tests: 4 passed.
Python compilation and git whitespace checks passed.
Stage measurements appear in `stage-results.log`.
CPU measurements appear in `cpu-recording.json` and `cpu-display-paused.json`.
The successful recording timing result appears in `surface32-recording-result.json`.
The first diagnosis remains in README.md as the record before these controlled tests.
