# Chimera deploy test log

## Post-restart PX4Sim check (2026-09-22)

- After the user restart, the RoboScout link initially worked at `10.200.142.62` and the onboard PX4Sim container was started manually.
- During the post-start warmup check, the drone stopped answering on both `10.200.142.62` and the former Wi-Fi address `192.168.1.9`.
- The laptop Ethernet carrier remains up and `RoboScout-wired` remains connected at `10.200.142.60/24`, but ARP for `.62` is incomplete and SSH is unreachable.
- No additional restart or network configuration change was made. PX4Sim camera/model and MAVLink telemetry still need verification after the drone is reachable again.

## PX4Sim front-door restart and telemetry check (2026-09-22)

- After the user restart, `./px4sim restart aircraft` completed successfully on d2. It rebuilt from cache, replaced the Compose network/container, and reported `onboard Up`.
- Vision is working: `/uas2/image` measured approximately 20–25 Hz. DeepStream loaded the requested prebuilt `yolo12l-custom-960.onnx_b1_gpu0_fp16.engine` and the injury engine without an engine build.
- The UAS2 ROS graph starts, including MAVROS, Foxglove, camera, gimbal, zoom, and detection nodes.
- PX4 telemetry is not working yet: `/uas2/state`, `/uas2/imu/data`, and `/uas2/altitude` have publishers/topics but no messages.
- Native `mavlink-router.service` is active and opens `/dev/ttyTHS1` at 500000 baud, but logs about 234–237 messages to unknown endpoints every five seconds.
- Router configuration still filters incoming source IDs with `AllowSrcSysIn = 2,255`. Confirm the flashed PX4 `MAV_SYS_ID` in QGC before changing this; do not blindly alter the filter.
- The obsolete `/etc/systemd/system/onboard.service` remains installed on d2 but is disabled/inactive. Removing it requires the drone user's sudo password; the deployment repository no longer installs or references it.

Last updated: 2026-09-22  
Target: `d2` at `192.168.1.9`  
UAS: `2`  
Airframe: Chimera v3  
Branch: `deploy-testing-chimera-v3`

## Important safety constraint

Do not run `sudo apt upgrade`, `dist-upgrade`, or an equivalent implicit package
upgrade on the aircraft. The NVIDIA SDK/JetPack package versions must remain
unchanged.

The deploy path now uses `apt install --no-upgrade` for package installation.
The first test exposed that plain `apt install` would have upgraded 13 existing
GStreamer packages; that transaction was interrupted during downloads before
package configuration. The corrected run reported `0 upgraded` for every apt
transaction. `dpkg --audit` was clean afterward.

## What was verified on the target

- Host is `d2`, Ubuntu 22.04.5, Jetson kernel `5.15.148-tegra`.
- NVIDIA runtime is present (`nvidia-smi` reports Orin / driver 540.4.0).
- The target uses `eth0`, not `eno1`.
- Existing DHCP address/default route is preserved:
  - `192.168.1.9/24`
  - default via `192.168.1.1`
- `10.200.142.62/24` is active as a secondary address on `eth0`.
- EchoTherm built and installed successfully.
- EchoTherm v4l2 loopback is `/dev/video6` and `echothermd` is running.
- Native MAVLink router and chrony are active.
- `rcam.service` is enabled but currently stopped intentionally.
- No reboot has been performed.

## Why the test stopped

The deploy script configured the IMX477 overlay in `/boot/extlinux/extlinux.conf`,
but the overlay is not active until a planned reboot. Before reboot,
`nvarguscamerasrc` reports `No cameras available`, so starting `rcam.service`
caused a 15-second watchdog failure and an automatic restart loop. The loop was
stopped. The script now starts `rcam` only after a one-frame Argus readiness
check succeeds; otherwise it leaves the service enabled but stopped.

The onboard PX4Sim step was initially blocked because the target did not have:

```text
/home/user/ros2_ws/src/5g_drone
```

The ground git daemon at `10.200.142.60:9418` was also unreachable during the
test. `remote/deploy_onboard.sh` now fails early with this prerequisite instead
of partially changing the target.

## Continued test progress

- The flight repositories were cloned to the target over a temporary,
  read-only Git daemon on the ground station at `192.168.1.8:9418`. This was
  only a Wi-Fi test path; the intended field path remains the RoboScout link
  and `10.200.142.60`.
- `5g_drone`, `MAVInsight`, `cdcl_umd_msgs`, `px4_msgs`, and `px4-sim-stack`
  are present on the target. The MAVROS and angles submodules were also
  copied into the target deployment checkout.
- The required model assets were copied from the ground `ros2_ws`.
  `fetch_models.py check --role onboard` reports all four required files
  present and matching.
- `remote/deploy_onboard.sh` completed successfully; the obsolete
  `onboard.service` lifecycle path is being removed. PX4Sim is the sole stack
  lifecycle front door.
- The Orin model directory now has a deploy-owned override selecting the
  verified `yolo12x-custom-1280` detector. The doctor still warns until the
  TensorRT detector/classifier engine filenames are built or supplied; this
  is a warning in the current doctor check, not a package or network failure.
- The only current doctor failure is `rcam.service` being inactive. It remains
  stopped because the IMX477 overlay has not been activated by reboot, and the
  pre-reboot Argus test reported no camera. No reboot or PX4Sim start has been
  performed.

## Ground-station networking sequence

`local/share-on.sh` runs on the ground station, not on the drone. It enables
forwarding/NAT from the ground station's internet interface to its
`10.200.142.*` Ethernet interface. After the ground station is connected and
sharing is enabled, the drone should use:

```bash
sudo ip route replace default via 10.200.142.60 dev eth0
```

Do not run that route command before the ground-side sharing link is ready.

## Deploy timing observations

The master script prints section estimates, measured section duration, and total
elapsed time. Observed timings on this target included:

| Section | Observed result |
| --- | --- |
| Identity/environment | ~3 seconds after sudo authentication |
| RoboScout address | immediate |
| EchoTherm first install/build | several minutes, including package installation and compilation |
| Camera overlay file update | ~4 seconds |
| RTSP dependencies/service install | ~25 seconds |
| EchoMAV/MAVLink router install/build | ~3 minutes |
| Chrony install/configuration | ~35 seconds |

These estimates should be updated after a successful end-to-end run with the
flight repositories available.

## Likely legacy work to remove or split later

PX4Sim's aircraft profile is expected to own the containerized flight stack, but
the PX4Sim documentation says the aircraft still keeps native `rcam.service`
and `mavlink-router.service`. Therefore do not remove those two native services
without verifying the aircraft profile's interfaces first.

Candidates for removal or separation from the minimal aircraft deploy are:

- The broad EchoMAV installer path that installs Cockpit, Cockpit storage and
  package-management UI, `temperature.service`, and extra tools. PX4Sim may not
  require all of these.
- Rebuilding/installing MAVLink Router from GitHub on every deploy if the
  required router binary/service is already supplied by the image or SDK.
- The large post-`exit 0` ROS/ML/CUDA/MAVROS installation block in `deploy.sh`.
  It is currently unreachable and should not be part of the single-run deploy
  until each dependency is explicitly required and pinned.
- Any `apt autoremove` behavior. It is currently after the early exit, but it
  should remain excluded from the minimal deploy because it can remove packages
  needed by the SDK or camera stack.

Keep and verify before considering removal:

- IMX477 device-tree overlay configuration.
- EchoTherm daemon and v4l2 loopback support.
- GStreamer RTSP dependencies used by native `rcam`.
- Chrony/time synchronization remains a host prerequisite for PX4Sim.
- Native MAVLink routing, unless PX4Sim's aircraft profile demonstrably replaces
  it without changing the documented UDP/UART interfaces.

## Source audit for the real aircraft/ground use case

The PX4Sim source confirms that the drone must use only the `aircraft` profile
(`onboard` plus `ros-base` during builds), while the laptop uses the `ground`
profile. The laptop's `./px4sim ui`, ground Foxglove bridge, and
`chimera_real.json` layout are ground-side functions. The drone's onboard
container already includes the `chimera_real` Foxglove bridge/control nodes;
the native `rcam` and MAVLink router remain required interfaces.

The deploy script now avoids the broad EchoMAV installer when
`mavlink-routerd` is already present. If a fresh image lacks the router, it
prompts before taking the legacy installer path. The legacy path is documented
in `legacy/README.md`. The old unreachable post-`exit 0` ROS/ML/CUDA install
tail is still present in the working file pending a clean removal patch; it
cannot execute, but should be deleted before merging the branch.

The old native ROS aliases, Cockpit, `temperature.service`, helper tools, and
simulator-only profiles are not used by the stated workflow. They should not
be installed by a routine aircraft deployment; existing legacy packages on d2
were left untouched during this review to avoid an unapproved removal while
the camera and PX4Sim startup remain unverified.

The active `remote/.bash_aliases` now follows the laptop's thin `pxs` style:
`alias pxs='cd ~/px4-sim-stack && ./px4sim'`. Native launch,
camera-forwarding, recording, calibration, multi-aircraft, and duplicated
status/log/doctor aliases were removed from the active file.

## Files changed for this test

- `deploy.sh`: model prompt, v2/v3 network paths, timing output, no-upgrade apt
  installs, camera readiness gating, and detached/idempotent EchoTherm launch.
- `remote/deploy_onboard.sh`: honors the selected model, tolerates the target's
  broken submodule metadata during branch lookup, and preflights `5g_drone`.
- `README.md`: documents v2/v3 behavior and ground-side internet sharing.
- `submodules/EchoTherm-Daemon/install.sh` and
  `submodules/echopilot_deploy/deploy.sh`: local test copies use
  `--no-upgrade`; these submodules are modified working trees and need a proper
  upstream/patch strategy before the branch is considered shareable.

## Resume checklist

1. Connect the ground station to the RoboScout link.
2. Run `./local/share-on.sh` on the ground station.
3. Confirm the drone can reach `10.200.142.60:9418`.
4. Plan and explicitly approve the reboot to activate the camera overlay.
5. Rerun the deploy script; it should skip the completed thermal install, pass
   the camera readiness check after reboot, and continue to the PX4Sim
   preflight.
6. Run `./px4sim doctor` before starting or restarting PX4Sim.

## PX4Sim aircraft verification on d2 (2026-09-22)

- The aircraft images built successfully on UAS 2 with pinned ROS, CUDA 12.6,
  TensorRT 10.3.0.30, MAVROS, PX4 messages, `tracking_test`, and the YOLO
  parser. The ARM64 build took about 53 minutes; the slowest stages were
  `px4_msgs` (~41 minutes) and the MAVROS patch (~53 minutes). No host
  `sudo apt upgrade` was run.
- `./px4sim start` brought up the onboard container. The camera path now
  produces `/uas2/image` at about 30 Hz, and the prebuilt
  `yolo12l-custom-960.onnx_b1_gpu0_fp16.engine` loads successfully. The
  `yolo12l-custom-960` ONNX, labels, and engine were copied from the laptop
  because the current `5g_drone` model manifest does not include them.
- UAS2's source parameters refer to missing placeholder zoom calibration
  files. The deployment overlay now uses the installed 1920x1080
  `90deg-cil034` calibration as a temporary UI/sensor fallback for all three
  presets. It is not a final D2 localization calibration and must be replaced
  after D2-specific calibration is available.
- `rcam.service`, `mavlink-router.service`, and `chrony` remain active; the
  drone still has DHCP/default routing on Wi-Fi plus persistent
  `10.200.142.62/24` on `eno1`. No RoboScout internet sharing was enabled.
- Remaining blocker: MAVROS telemetry is silent (`/uas2/altitude` has no
  samples), while `mavlink-routerd` reports roughly 235 messages to unknown
  endpoints every five seconds. Its generated filters currently allow source
  sysids `2..255`; the flight controller may be emitting sysid 1. Confirm the
  FCU sysid before changing the native router filter, then restart only
  `mavlink-router` and the onboard container if required. Do not change this
  blindly while the aircraft is operating.
- The generic `./px4sim verify vehicle`/`foxglove` stages assume `FIRST_UAS=1`
  even on this real UAS2 aircraft. Direct checks should use `/uas2/*` until
  the px4-sim-stack verification helper is made vehicle-aware.
- Important non-blocking warnings include the missing optional ReID model,
  missing `lsmod`/`modprobe` inside the container, software video fallback,
  15 W power mode, and 15 GB host RAM.
