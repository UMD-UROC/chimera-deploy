# Surface headroom and other stream risks

## Decoder limit and the old 96 setting

The installed d1 `nvv4l2decoder` accepts `num-extra-surfaces` from 0 through 55.
The driver also supplies its minimum decode surfaces. Thus, 55 is the extra count, not the total count.
The RGB H.264 producer now requests 55, the supported maximum.
The process logs its actual property value as `RGB_DIAG_CONFIG num-extra-surfaces=55`.

At 1920x1080 NV12, one tightly packed surface requires 3,110,400 bytes.
The increase from 32 to 55 therefore costs about 68.23 MiB, before alignment and allocation metadata.
The 55 extra surfaces alone require about 163.15 MiB on that basis.
These are storage estimates. Shared NVMM allocations do not map directly to process RSS.

The old 96 value is in `5g_drone/config/param_files/onboard_common_params.yaml`.
It belongs to the DeepStream source configuration, downstream of the native camera producer.
Both host and onboard-container `gst-inspect` show that the installed `nvunixfdsrc` lacks this property.
`NvUnixSource` checks for the property before setting it. The 96 value therefore adds no surfaces on this installation.
It never configured the camera server's H.264 decoder.

The 5g_drone branch changes that configuration to 55 and corrects the misleading source comments.
This also keeps the common value within the installed decoder limit if a decoder-based source uses it later.
The installed raw socket source still ignores it.

## Other streams

The confirmed bottleneck is H.264 decoding, not H.264 encoding.
The USB camera encodes H.264. The native camera server decodes it, shares raw NV12, then H.265 encoders serve and record it.

| Path | Similar weakness | Current evidence |
| --- | --- | --- |
| RGB H.264 input | Decoder output surfaces can run out while consumers retain buffers. | Reproduced and controlled through the extra-surface comparison. |
| RGB MJPEG alternative | Uses the same decoder pool policy as H.264 after consolidation. | Both generated pipelines request 55 extra surfaces. A live MJPEG capture test remains separate. |
| Pilot CSI input | Finite camera and converter pools feed several raw consumers. | Pilot continued through the original long RGB outages. Equivalent starvation is not demonstrated. |
| Thermal raw USB input | Finite capture and converter pools feed several raw consumers. | Thermal is not active in the day configuration. No equivalent runtime test was possible in this session. |
| All raw output branches | One-buffer queues discard old frames under bursts or slow consumers. | RGB overrun counters confirm drops, including with adequate decoder headroom. |
| All H.265 output encoders | Encoders retain input buffers and share compute and memory bandwidth. | Resource contention is possible. No encoder defect was established. |

The installed `nvvidconv` defaults to four output buffers.
Producer branches do not explicitly increase that pool.
An element that passes buffers through can also leave downstream consumers tied to upstream allocations.
The actual retention and copy behavior needs measurement before a converter-pool change.
A larger decoder pool does not enlarge every converter or consumer pool.

The watchdog watches each producer tee, but a watchdog timeout exits the entire camera server.
Thus, one camera that stalls for 15 seconds can restart otherwise healthy camera streams.
Explicit producer errors have a separate retirement path, so error handling and timeout handling differ.

## Limits of more surfaces

More surfaces absorb bounded buffer retention. They do not repair a buffer leak or an indefinitely blocked consumer.
A count of 55 cannot guarantee the absence of starvation for all future workloads.
Keep frame-age and stage counters to detect a recurrence.
The raw queues still trade completeness for low latency.
Their overrun counts must remain separate from decoder health.
Do not apply a large pool count to every 4K converter without a measured retention and memory budget.

## Validation method

The runtime check uses ROS bag plus video recording from the drone's px4sim UI.
The camera process logs the actual decoder property value, rather than relying on the source file alone.
The recording analyzer uses tsdemux and h265parse to count access units without decoding pixels.
On the earlier 32-surface recording, it matched ffprobe: 2,279 units over 81.970022 seconds.
This checks the analyzer before its use on the new recordings.

## 55-surface test result

The UI recorded both streams for about 125.6 seconds in `rosbag2_2026_10_29-14_54_16-air-d1`.
RGB: 3,500 access units over 125.591556 seconds, with a maximum gap of 0.140767 seconds.
Pilot: 3,578 access units over 125.593767 seconds, with a maximum gap of 0.189144 seconds.
Neither recording has a gap over 0.5 seconds or nonincreasing presentation timestamps.
Stage counters show 4,452 decoded frames over about 150 seconds including startup.
The maximum decoded gap is 0.303 seconds, including startup and stack restart activity.
No corrupt-buffer flag or producer starvation occurred in that interval.
Memory samples remained above 7 GiB available, with no swap use.
Recording stopped after the test.

The H.264 and MJPEG producer modes now share one decoder definition and one extra-surface constant.
Codec-specific caps, parsers, and the MJPEG decoder flag remain distinct.
A regression test checks both generated pipeline modes.

The unused `remote_start_camera_server.sh` is another legacy H.264 path with the decoder default.
The installed rcam service does not run it. Its lack of extra surfaces remains a legacy-path risk.
DeepStream's file and RTSP sources use the configured count through `_make_decoder`.
The onboard common value is now 55. The generic code default is 40, and simulation explicitly requests 55.
The inference batch converter sets its own calculated `output-buffers` count.
The native pilot and thermal converters use the installed `nvvidconv` default of four output buffers.
Those converter pools are separate from decoder extra surfaces and were not changed.
