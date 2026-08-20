# TODO: KLV geolocation

**This file is a snapshot for the next session. Nobody keeps it current. Read it one time. Then delete it.**

## What works now

The drone serves an `rgblk` mount. This mount carries H.265 video and MISB ST 0601 KLV metadata in MPEG-TS. The ground relay serves the same stream as `rgblk3` and `rgblk4`.

On uas3, `rcam.service` and `klv.service` are active. The stream runs at 30 Hz. Every KLV packet is 34 bytes long. A 34-byte packet holds a timestamp and a version number only. It holds no geolocation.

## The open blocker

`klv_geo_node` gets good localizations from tf_loc, but the answers arrive too late. The muxer sends each frame before its answer comes back. As a result, the stream carries no geolocation.

Measured round trip to `/uas3/tba_loczn`:

| Request rate | Median | Max | Budget |
|---|---|---|---|
| 5 Hz | 86 ms | 86 ms | 150 ms |
| 30 Hz | 520 to 777 ms | 1383 ms | 150 ms |

tf_loc polls the transform tree and holds an executor thread for each request. The executor has four threads. The service answers about eight requests each second. A rate of 30 requests each second overloads it.

### Next step

1. Set the `latency` property on `mpegtsmux` in `remote/rtsp_config.py`. A sparse KLV pad must not stall the muxer.
2. Set `KLV_FRAME_INTERVAL` to 6. This gives 5 Hz.
3. Restart `rcam.service` and `klv.service` on the drone.
4. Capture the stream. Then count the KLV packets longer than 100 bytes.

If you do step 2 before step 1, the mount answers 503 on PLAY. A test on the drone confirmed this failure.

## Facts you do not need to find again

- tf_loc registers the service as `/uasN/tba_loczn`. It does not register `/uasN/tf_loc/tba_loczn`. The name comes from the relative parameter `localization.service.tba_localization`.
- The KLV PES and the video PES carry the same PTS. The relay hop keeps them equal.
- The settle delay belongs to the request, not to the video path. Two queues in series do not split a delay. The downstream queue takes every buffer, so the upstream queue stays empty.
- An RTSP media runs at a one hour PTS offset. Compute buffer times from the running time, not from the raw PTS.
- The drone needs no pymavlink. tf_loc supplies all telemetry.
- GPS gives 9.6 Hz on average, but some gaps reach 1.1 s. Some frames always miss a fix.
- The message `points backwards!` is correct for a drone on the ground. A drone on the ground cannot intersect its own home plane.
- The drone clock and the laptop clock agree within 3 ms.
- The producers already make a spare socket for `rgblk`. The `PRODUCERS` table needs no change.

## How to work on this

- uas3 answers at 10.200.142.63. The units .61, .62 and .64 do not answer.
- `sudo` over SSH needs a password. The README gives `Talon240`. Rotate this password.
- To start the ROS nodes, use the `onboard` alias. Over SSH, use `setsid nohup`.
- To test for a running stack, look for `/uas3/tf_loc` in `ros2 node list`. Do not use `pgrep`, because it matches its own command line.
- To move the git repositories, use the `sync` alias. It runs `./setup_git_server.sh sync`.
- After a change to 5g_drone, build the workspace with `ccb`. Then start the stack again.

## Tests to build again

The bench harness was in a session directory, and that directory is gone. These four assertions found real bugs:

1. Compare `LOCALIZATION_SERVICE` with `TfLocalizationNode.PARAMS["localization.service.tba_localization"]`.
2. Measure the frame age when the request arrives. It must equal the settle time.
3. Compare the KLV PES PTS with the video PES PTS. They must be equal.
4. Count one KLV packet for each video frame.

A stub that serves the same name the node calls proves nothing about that name. Take the name from the source of truth.
