# C1 PRO coarse image sweep

Run one fast pass across the camera's image controls:

```bash
cd ~/chimera-deploy
python3 local/c1_daytest.py preflight
python3 local/c1_daytest.py start
```

The default is **one baseline plus 29 coarse cases**, with one full-resolution image and one measurement row per case.
There are no repeat rounds or baselines between cases.
Each case changes one control from the original settings. All other image controls return to their original values.
The suite restores all eight image controls after completion, stop, or a handled error.

The expected total runtime is 30–45 seconds on uas1.
The complete onboard smoke sweep took 32.7 seconds and saved 30 images and 30 measurements.
All eight image controls restored correctly. Twelve software tests passed.
The default settling period is 0.4 seconds per case. These quick samples show broad differences before a later fine test.
They do not establish that automatic exposure fully settled at each value.

## Coarse values

| Control | Values |
|---|---|
| Brightness | −64, −32, −16, 0, 32, 64 |
| Gamma | 72, 100, 200, 350, 500 |
| Contrast | 0, 16, 32, 48, 64 |
| Saturation | 0, 32, 64, 96, 128 |
| Sharpness | 0, 2, 3, 4, 6 |
| Hue | −40, −20, 0, 20, 40 |
| Backlight compensation | 0, 1, 2 |
| Anti-flicker (`power_line_frequency`) | 0 off, 1 for 50 Hz, 2 for 60 Hz |

The baseline supplies each control's original value, so the suite omits that value from its coarse cases.
The 30-case count assumes the current uas1 defaults. Other original values can change the count.
Controls absent from the camera are skipped and listed in `state.json`.
The sweep covers the available range endpoints and several coarse values between them.

Automatic exposure and automatic white balance remain enabled throughout the sweep.
The suite does not change manual shutter, gain, white balance temperature, or dynamic frame rate.
Those controls would interfere with the automatic behavior or frame timing requested for this test.
It does not move the lens, change the IR filter, alter calibration, or restart the camera server.
Brightness and gamma change the delivered image. They cannot prove recovery of clipped sensor detail.
Anti-flicker mostly matters under artificial light, but the suite includes it for coverage.

## Commands

```bash
python3 local/c1_daytest.py status
python3 local/c1_daytest.py stop
python3 local/c1_daytest.py fetch --destination ~/Downloads
```

Use a subset for an even shorter pass:

```bash
python3 local/c1_daytest.py start --parameters brightness,gamma,contrast
```

Use `--settle 2` if a later run needs more time for each control change.
`smoke` uses the same complete coarse sweep as `start`.
`observe --seconds 30` records the current image for 30 seconds without control writes.
`--seconds` sets the observation duration or measurement window. Sweep mode always saves just one sample per case.
Repeat rounds are not supported. Start a new run after moving to another scene.

The default aircraft is uas1 at `10.200.142.61`. Use `-d HOST` for another aircraft.
The camera path identifies uas1's C1 PRO by serial number. Another camera needs its own device path in the onboard command.
The aircraft must remain in RGB mode during a sweep. Do not change camera controls from another tool during a run.

## Results

Results remain on the aircraft in `~/c1-daytest-results/<UTC timestamp>-<action>/`.
Fetch copies the run directories to the chosen destination.
Each JPEG name identifies the case. `samples.csv` includes its control name, requested value, all control readbacks, UTC, and source timestamp.

| File | Contents |
|---|---|
| `state.json` | Original controls, complete case plan, script hash, run status, and restoration status |
| `events.jsonl` | Case changes and timestamps |
| `samples.csv` | Image measurements, control values, resource use, and image names |
| `*.jpg` | One reference image per case at 1920×1080, JPEG quality 95 |
| `controls-before.txt` | Initial controls and flags |
| `controls-restored.txt` | Controls after restoration |
| `camera-info.txt` | Camera identity |

Measurements include brightness, clipping, shadows, color ratios, and sharpness.
The upper-third and lower-half regions are geometric regions. They do not identify sky or ground.
Channel clipping means any channel at or above 250. White clipping means all channels at or above 250.
Shadow pixels have luma at or below 16. Luma uses `0.299 R + 0.587 G + 0.114 B` on decoded pixels.
Sharpness uses half-resolution Laplacian variance. Texture, motion, and noise affect this measure.
The shutter and gain readbacks can be inactive or stale under automatic exposure.
Source timestamps describe the pipeline, not sensor exposure times.

The reader uses the existing `/tmp/rgb_nv.sock` output at five frames per second.
Images come after H.264 decoding and before H.265 encoding. No extra radio stream or USB capture session is required.

## Stop and recovery

The onboard user service continues after SSH disconnects. Uas1's desktop session keeps the user service available.
A lock prevents simultaneous suite processes. The service has a runtime limit and reduced CPU priority.
It also runs a separate restoration command after process termination, including a forced kill.

Missing frames, non-advancing timestamps, camera-server restarts, changed automatic modes, or unexpected control values stop the sweep.
The suite records the error and attempts restoration. Camera disconnection or power loss can prevent immediate restoration.
After the camera returns, explicit recovery uses the saved run directory:

```bash
# On the aircraft. Replace RUN with the saved directory name.
python3 ~/.local/share/c1-daytest/c1_daytest.py restore \
  --output ~/c1-daytest-results/RUN
```

The wrapper copies the runner into `~/.local/share/c1-daytest/`, outside the aircraft checkout.
It does not install packages or need sudo.

## Software checks

```bash
python3 -m unittest discover -s remote -p test_c1_daytest.py -v
python3 -m py_compile local/c1_daytest.py remote/c1_daytest.py
```
