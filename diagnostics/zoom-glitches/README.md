# RGB zoom diagnosis, 2026-10-29

## Findings

The supplied bag confirms long RGB outages in two independent consumers.
The evidence points to the shared RGB path, but does not identify the failed stage.
CPU saturation is a strong suspect. Hardware failure remains unproven.
No runtime fix was deployed. No services, camera settings, or drone files changed.
The live check added one RTSP client for about 20 seconds.

## Recorded evidence

Input: `/home/user/ros2_ws/rosbag2_2026_10_29-14_18_09-air-d1`.
Use `python3 diagnostics/zoom-glitches/packet_gaps.py VIDEO.ts` to repeat the packet analysis.
This tool reads video stream zero. It does not decode pixels.
Packet presentation order can differ from decode order with other encoders.
The measured files have no nonincreasing packet presentation timestamps.

| Stream | Video packets | PTS span | Largest gaps |
| --- | ---: | ---: | --- |
| RGB recording | 342 | 29.248856 s | 8.615856 s and 8.627600 s |
| Pilot recording | 1061 | 36.468745 s | 0.135234 s |
| Live RGB over RTSP/TCP | 562 | 19.873 s | about 0.136 s |

RGB recording gaps start at offsets 4.707 s and 17.708 s from its first packet.
Several smaller gaps last 0.132–0.136 s.
The live sample also contains repeated gaps of this size.
The live sample did not reproduce the long outages.

The ROS image topic `/uas1/image` contains 322 messages.
Its arrival gaps exceed seven seconds three times:

| Last arrival, Unix seconds | Gap |
| --- | ---: |
| 1793297898.250 | 9.054 s |
| 1793297911.253 | 9.060 s |
| 1793297923.275 | 7.497 s |

The heartbeat reports zero image rate during these outages.
All 37 `/ds/status` samples report level OK and message `running`.
This is a confirmed gap in health reporting.
The `recording=idle` field describes the DeepStream recorder, not the separate shell recorder.

FFmpeg decoded the full RGB recording without H.265 decode errors.
Its null output reported timestamp collisions at the output time base.
Packet timestamps remain strictly increasing, so these warnings do not prove damaged timestamps at capture.
One-second contact sheets showed no clear pixel damage.
This sampling cannot exclude brief pixel damage.
The recording contains re-encoded H.265, not the original USB H.264.
A valid H.265 recording cannot prove that the original H.264 frames were healthy.

## Live drone evidence

Host `user@10.200.142.61` reports hostname `d1`.
At about 14:35–14:37 EDT, load averages were about 22–24 on eight CPU cores.
Two tegrastats samples show CPU use of 84–100% per core at 1497 MHz.
The power mode is 25W. CPU temperature was about 56 C, with no swap use.
These samples establish load during inspection, not CPU use during the supplied recording.

The C1 PRO H.264 endpoint is `/dev/video5`, at 1920x1080 and 30 fps.
It uses a 480 Mbps USB bus through hubs.
The boot log shows no C1 PRO disconnect or explicit RGB transport failure.
It does show a Boson disconnect at 14:14:10.
The camera server disabled the Boson through day/night selection at startup.
Thus, active thermal streaming cannot explain this recording through shared USB bandwidth alone.

Local and drone copies of `remote/rtsp_config.py` and `remote/forked_rtsp_server.py` have matching SHA-256 hashes.
The drone camera server started at boot. Source equality does not prove which bytes its process loaded at startup.

## Source review

`remote/rtsp_config.py` sends USB H.264 directly through `h264parse` and `nvv4l2decoder` before the raw tee.
There is no separate queue between USB capture and decode.
Decoder backpressure can therefore delay capture. This is a candidate mechanism, not a measured cause.

All four raw branches use one-buffer queues that discard old frames.
`remote/record_nv_streams.sh` adds another such queue before H.265 encoding.
These queues explain intentional frame loss under load. They do not alone explain damaged pixels or nine-second outages.
There is no configured leaky queue before H.264 decoding in this producer.

`ProducerFrameWatchdog` in `remote/forked_rtsp_server.py` watches the raw tee only.
Its 15-second timeout misses these shorter outages.
It does not count corrupt input buffers, capture sequence gaps, or branch queue overruns.

The DeepStream source uses a separate `rgbds` socket.
Its image outages make a fault confined to the shell recorder less likely.
Shared decoder starvation, capture loss, raw surface pressure, and consumer backpressure remain candidates.

Reviewed source revisions:

- chimera-deploy: `b461722fb7647ec6c2c80f3286df301473587ebd`
- px4-sim-stack: `0ed4266ec4aaa211512990bd5a4fecd95a02b448`
- 5g_drone: `9cb6ed072a2ea95b43c95c52665eeddd87e712b0`

## Next experiment and health design

Instrument the existing producer in a later approved runtime test.
A second process must not take the occupied USB capture endpoint.

1. Count source buffers, sequence gaps, timestamps, and CORRUPTED/DISCONT flags before H.264 parsing.
2. Count parsed access units and decoded frames. Record the last arrival time at each stage.
3. Count queue overruns and deliveries on each raw branch. Compare recorder and DeepStream arrival gaps.
4. Save a bounded original H.264 sample with these counters during a failure. Decode it separately.
5. Compare identical loads with recording enabled and disabled, then test CPU load reduction.

Keep any compressed queue bounded and non-leaky.
Dropping arbitrary H.264 reference frames can damage later dependent frames.
A queue may absorb short delays, but cannot solve sustained overload.
Do not apply this candidate change without stage measurements.

Publish frame age, source rate, decoded rate, and branch loss separately from process liveness.
Use a short configurable stale threshold, initially about 0.5 seconds for this 30 fps source.
Keep explicit states for transport error, decoder error, stale stream, and unknown pixel health.
A decoder can conceal damage. Absence of an error flag must not imply healthy pixels.
If reference loss occurs, track recovery through a clean random-access frame and decoder recovery.
Preserve source timing and health metadata across the raw socket boundary where the plugin permits it.
The installed plugin defaults `buffer-timestamp-copy` to false, and consumers use `do-timestamp=true`.
Current consumer timestamps therefore do not establish original capture age.

The next diagnosis needs these counters to separate a camera fault from a software pipeline fault.
