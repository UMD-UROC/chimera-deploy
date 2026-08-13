# MAVROS patch for PX4 v1.18

## The problem

PX4 v1.18 removed the legacy command shims from `mavlink_receiver.cpp`. In
v1.17 the receiver translated three old commands into the generic
`MAV_CMD_REQUEST_MESSAGE`:

```
	// First we handle legacy support requests which were used before we had
	// the generic MAV_CMD_REQUEST_MESSAGE.
	if (cmd_mavlink.command == MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES) {
		result = handle_request_message_command(MAVLINK_MSG_ID_AUTOPILOT_VERSION);
```

That block is gone in v1.18. `MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES` (520)
now reaches the default case and the FCU answers `MAV_RESULT_UNSUPPORTED` (3).

MAVROS 2.14.0 still asks with command 520, so it never learns what the
autopilot can do. The `sys` plugin retries five times and then gives up:

```
[WARN]  [uas1.cmd]: CMD: Unexpected command 520, result 3
[WARN]  [uas1.sys]: VER: broadcast request timeout, retries left 4
[ERROR] [uas1.sys]: VER: command plugin service call failed!
[WARN]  [uas1.sys]: VER: your FCU don't support AUTOPILOT_VERSION, switched to default capabilities
```

The gimbal answers on component 154, which is why the log fills with
`VER: 1.154:` lines. MAVROS only stores capabilities from its target
component (1.1), so those replies do not stop the retries.

This is not only log noise. `get_default_caps()` in `mavros/src/lib/uas_ap.cpp`
returns `0`, so after the fallback MAVROS believes the autopilot supports
nothing. `MAV_PROTOCOL_CAPABILITY_MISSION_INT` is part of what it loses, so the
waypoint plugin stays on the deprecated `MISSION_ITEM` protocol, which carries
waypoints as float32 degrees instead of int32 1e7 degrees.

## The fix

`0001-sys_status-request-AUTOPILOT_VERSION-via-REQUEST_MESSAGE.patch` changes
two lines in `mavros/src/plugins/sys_status.cpp`. It asks with
`MAV_CMD_REQUEST_MESSAGE` (512) and passes the AUTOPILOT_VERSION message id
(148) in param1.

PX4 v1.15, v1.16, v1.17 and v1.18 all handle command 512, so the patch is safe
to leave in place if the aircraft goes back to an older firmware.

## Applying it

```bash
cd ~/chimera-deploy
git submodule update --init submodules/mavros submodules/angles
./remote/mavros_patch/apply.sh
```

The script builds an overlay workspace at `~/mavros_ws`. It does not touch
`/opt/ros/humble`, so apt keeps ownership of the installed packages, and `ccb`
does not rebuild MAVROS on every launch.

`angles` is built from a submodule because it is a MAVROS build dependency that
is not installed on the aircraft, and the aircraft has no internet.
`mavros_msgs`, `libmavconn` and `mavros_extras` stay on the apt packages.

The `ws` alias sources `~/mavros_ws/install/setup.bash` last, which puts the
overlay ahead of `/opt/ros/humble` in `AMENT_PREFIX_PATH`. Sourcing it earlier
does not work: `rs` re-sources `/opt/ros/humble` and moves it back to the front.

## Checking it worked

Launch, then look for these lines instead of the timeout warnings:

```
VER: 1.1: Capabilities         0x000000000004e8ff
WP: Using MISSION_ITEM_INT
```

`0x4e8ff` is the real capability word from the flight controller, and `1.1` is
the autopilot. Replies logged as `1.154` come from the gimbal and do not count.

## Removing it

```bash
rm -rf ~/mavros_ws
```

The `ws` alias then falls back to the apt MAVROS on its own.
