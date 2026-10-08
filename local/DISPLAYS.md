# Ground-station display layouts

`display-layout` mirrors or extends connected monitors in an X11 desktop
session. The built-in display keeps its preferred native resolution and refresh
rate. External displays use their advertised preferred modes; there are no
monitor brand, serial-number or connector-name restrictions.

## Install

Run as the desktop user, without `sudo`:

```bash
sudo apt install x11-xserver-utils python3-gi libnotify-bin
./local/display-layout install
```

For the NVIDIA backend, `nvidia-settings` must already be available with the
machine's installed driver. Installation does not install or change drivers.
The command uses the Python standard library; `python3-gi` provides GNOME
display identification and shortcut installation.

The installer copies the command to `~/.local/bin/display-layout`, adds **Mirror
Displays** and **Join Displays** to the application menu, registers **Ctrl +
Super + M/J**, and creates a login entry. Reinstall after updating this checkout.
It preserves unrelated custom shortcuts and does not change the active layout.
If `~/.local/bin` is not on `PATH`, use `~/.local/bin/display-layout` or run the
repository command directly. `local_setup.sh` includes the installation step.

## Commands

```bash
display-layout mirror                       # Mirror the laptop to every connected monitor
display-layout join                         # Place external monitors to the right
display-layout mirror --dry-run              # Inspect the selected modes and command
display-layout mirror --backend xrandr       # Use generic RandR scaling
display-layout join --backend xrandr
display-layout mirror --backend nvidia       # Require NVIDIA-controlled outputs
```

`--backend auto` is the default. It uses NVIDIA when all connected outputs are
controlled by NVIDIA, including an external monitor of any brand. Other output
combinations use RandR. Each request chooses one configuration from advertised
modes and applies it once. It does not search through resolutions or retry a
failed configuration using another backend.

| Backend | External image | Built-in image |
| --- | --- | --- |
| NVIDIA | Fits proportionally, with black bars when aspect ratios differ | Native resolution, without resampling |
| RandR | Fills the monitor; differing aspect ratios can stretch the image | Native resolution, without resampling |

The RandR command sets the framebuffer size explicitly, clears existing driver
borders when that property is available, and uses `--nograb` so GNOME can process
display events during the change. It does not enable panning. This avoids the
incorrect image regions and repeated resets seen when scaling was applied over
the previous NVIDIA border configuration.

## Shortcuts and login

**Ctrl + Super + M** runs `display-layout mirror`; **Ctrl + Super + J** runs
`display-layout join`. Super is usually the Windows-logo key.

**Super + P** continues to use GNOME's built-in display switcher. Its Mirror
option can fail when the displays have no common physical resolution. These
shortcuts use scaled mirroring instead and do not alter Super + P.

The login entry runs `display-layout auto`. It restores mirroring only when the
last successful command was `mirror`, waiting up to 30 seconds for an external
monitor to appear. A successful `join` stops mirroring from being restored at
login. A failed change is not retried at login. Connecting a monitor later in
the session does not automatically change the layout; press Ctrl + Super + M.

## Recovery and limits

Before changing displays, the command saves the existing layout. Configuration
commands have an eight-second timeout. A failed command or failed verification
restores the saved layout immediately. An independent watchdog restores it
after 15 seconds if the caller stalls or exits before completing the change.
Successful changes cancel the watchdog.

State is kept in `$XDG_STATE_HOME/display-mirror`, normally
`~/.local/state/display-mirror`. The latest result is `last-result.json`;
`previous-working-layout.json` contains the previous layout. To restore that
snapshot manually while the same monitors are connected:

```bash
display-layout --recover ~/.local/state/display-mirror/previous-working-layout.json
```

This command requires X11; it does not configure a Wayland session. Cable,
dock, GPU bandwidth and driver limits still apply. Recovery also depends on a
responsive display server and the saved monitors remaining connected.

Mirror and Join have been tested on the Ubuntu 22.04 NVIDIA ground station with
a native 3840×2400, 120 Hz laptop display and a 1920×1080, 60 Hz Dell monitor,
including transitions between NVIDIA and generic RandR layouts. Other
resolutions, multiple outputs and failed-change recovery are covered by
automated tests:

```bash
python3 -m unittest discover -s local -p 'test_display_layout.py'
```
