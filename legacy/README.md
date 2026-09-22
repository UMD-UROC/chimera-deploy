# Legacy Chimera installs

These are retained for recovery and older aircraft, but are not part of the
PX4Sim aircraft deployment by default.

## EchoMAV broad installer

`submodules/echopilot_deploy/deploy.sh no-static` installs or rebuilds
MAVLink Router and also installs Cockpit, `temperature.service`, and helper
tools (`nano`, `nload`, `htop`, and `picocom`). The current deploy script only
offers this path interactively when `mavlink-routerd` is missing.

The PX4Sim aircraft path needs the native MAVLink Router service and its
configuration, but does not use Cockpit, the temperature logger, or those
helper tools. Do not run this installer during routine PX4Sim deployment.

## Legacy native ROS aliases

The old `uspi*`, `onboard-native`, and direct launch aliases are for the
pre-container deployment. A provisioned aircraft should use:

```bash
cd ~/px4-sim-stack
./px4sim start       # aircraft container on the drone
./px4sim ui          # ground-side UI on the laptop
```

Repository synchronization remains the laptop-side `setup_git_server.sh sync`
workflow; it is separate from the old native ROS launch aliases.
