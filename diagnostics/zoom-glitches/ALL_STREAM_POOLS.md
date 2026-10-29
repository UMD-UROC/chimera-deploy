# All-stream pool policy and acceptance

The shared policy is `5g_drone/umd_uas/video_pool_policy.py`.
See [the policy guide](../../../ros2_ws/src/5g_drone/docs/video_pool_policy.md) for NVIDIA references and memory estimates.
The native adapter reads this same source through the configured sync workspace paths.
No v2/v3 or camera selector limits the policy.

## Final values

| Stage | Policy |
| --- | --- |
| Hardware decoder | 55 extra surfaces, limited to installed plugin support |
| Native pilot, RGB, thermal converters | 32 output buffers |
| Direct recorder and legacy converters | 32 output buffers |
| DeepStream capture and recording converters | Target 32, with a 512 MiB stage budget |
| JPEG preview converter | 16 output buffers |
| Inference converters | Shared target and aggregate budget, with validated minimums |
| Multiplexer output pools | Shared target and budget, when the property exists |

A 4K RGBA single-slot pool stays at 16 buffers, about 506 MiB before padding.
An eight-slot 4K RGBA inference chain preserves four buffers per slot, about 1 GiB across slots.
Validated minimums take precedence over the budget target.
The source, simulation, native, and inference defaults no longer maintain separate pool counts.

The native service also watches its configuration and the policy file.
A sync that changes them causes a controlled exit and systemd restart.
The final deployment test observed `Camera source or pool policy changed; restarting rcam.`
This removes the need for manual native-camera process signals on future policy updates.

## Why the preview has a separate limit

A clean run with 32 preview buffers failed in the Jetson hardware JPEG path.
At 15:14:21 EDT the node logged `NVJPGPushSurfFalconMethodRelocShift` failures
for `SET_CUR_PIC_CHROMA_U` and `SET_CUR_PIC_CHROMA_V`, followed by a stream flush error.
The earlier exploratory run also failed. Its separate pipeline-construction checks were not the sole explanation.

Only the JPEG preview converter pool changed from 32 to 16 for the successful run.
Native converters, decoder headroom, other DeepStream converters, and multiplexer pools kept their larger settings.
This isolates a sensitive setting, but does not establish a documented 16-buffer hardware limit.
It also does not identify the exact vendor driver defect.

A larger output pool supplies more distinct buffers and DMA descriptors over the stream's lifetime.
It can expose registration, buffer-lifetime, synchronization, or bookkeeping problems independently of total available RAM.
These are candidate mechanisms, not a proven explanation for this failure.
The final configuration uses the larger tested working preview value instead of assuming that every maximum is safe.

## Final recording

The front-door acceptance run used `sync` and the aircraft's `px4sim ui` recording controls.
It produced `rosbag2_2026_10_29-15_16_20-air-d1` on d1.
No additional hardware pipelines were constructed during this run.

| Output | Samples | Span | Largest gap |
| --- | ---: | ---: | ---: |
| RGB H.265 recording | 3715 | 133.292 s | 0.140 s |
| Pilot H.265 recording | 3765 | 133.362 s | 0.265 s |
| ROS JPEG images | 2959 | 116.221 s | 0.217 s |

ROS subscriptions appeared after the video recorders started, so their measured spans differ.
Neither video has nonincreasing presentation timestamps or a gap above half a second.
The ROS image stream has no gap above half a second.
Twenty sampled ROS JPEGs decoded successfully.
Two zero-rate heartbeats occurred at startup, before the image interval. They were not sustained outages.
No hardware JPEG errors appeared in the final run's service logs.
Available memory was about 7.5 GiB at the end, with no swap use.

The earlier 197-second recording with larger pools also kept both H.265 streams active.
It failed the preview check and was not accepted as a healthy complete stack.
Its six memory samples ranged from 6.72 to 7.21 GiB available, with no swap use.

## Checks and scope

- Shared policy tests: 8 passed, including aggregate budgets and older plugin limits.
- DeepStream unit tests: 96 passed.
- Native camera configuration tests: 11 passed, including both airframe models and camera selections.
- Native watchdog and source reload tests: 5 passed.
- Recording lifecycle tests: 28 passed.
- Native parse checks: 18 producer/factory combinations, covering both RGB codecs and all three camera types.
- DeepStream construction checks: 1080p, 4K, and thermal geometries reported the expected converter and multiplexer pools.

The system pytest plugin set was incompatible with the installed pytest version.
The isolated pytest runs disabled automatic third-party plugin loading.
The tests themselves then passed.

All source changes were made locally on `bugfix/zoom-glitches`, committed, and pushed.
D1 received the policy through sync. D2, D3, and D4 were offline.
Their next sync uses the same source policy and native reload behavior.
Thermal and other airframes received configuration and parse coverage, not physical capture tests in this session.
The inference pool budgeting preserves the existing known working minima. No new full-load inference benchmark was run.

More surfaces cannot eliminate sustained CPU overload or indefinitely retained buffers.
One-buffer leaky queues still discard frames under bursts to bound live latency.
