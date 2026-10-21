# C1 PRO daytime image tests

Run the preflight on the ground before the flight test:

```bash
cd ~/chimera-deploy
python3 local/c1_daytest.py preflight
```

The default aircraft is uas1 at `10.200.142.61`. Use `-d HOST` for another aircraft.
The default camera path identifies uas1's C1 PRO by serial number.
Another camera needs its own device path in the onboard command.

## Flight commands

1. Start the comparison when the aircraft has a useful daytime view:

   ```bash
   python3 local/c1_daytest.py start
   ```

2. Check progress:

   ```bash
   python3 local/c1_daytest.py status
   ```

3. Stop early if necessary:

   ```bash
   python3 local/c1_daytest.py stop
   ```

4. Copy the results to the laptop:

   ```bash
   python3 local/c1_daytest.py fetch
   ```

The onboard user service continues after SSH disconnects. Each run ends automatically.
The user service needs an active onboard user session. Uas1's desktop session supplies it.
The default comparison has 13 blocks, with 30 seconds of measurement and at least 8 seconds of settling per block.
Allow about 9 minutes. Two rounds rotate the candidate order and place the original settings before each candidate.
Use `start --seconds 60 --rounds 3` for longer blocks and more repeats.
The aircraft must remain in RGB mode during the test.
Do not use another tool to change camera controls during a run.

`observe --seconds 120` records the original image without control writes.
`smoke` runs one short round on the ground, with 3-second measurement blocks and 2-second settling periods.
Smoke results test the software path. Their short settling periods do not support a quality decision.

## Automatic controls and candidates

Automatic exposure and automatic white balance must already be enabled.
The suite checks them throughout each run. It never writes manual shutter time, gain, white balance, or dynamic frame rate.
It does not move the lens, change the IR filter, alter calibration, or restart the camera server.

| Profile | Backlight compensation | Brightness |
|---|---|---|
| Baseline | Original | Original |
| Auto, backlight off | 0 | Original |
| Auto, backlight off, brightness minus 4 | 0 | Original minus 4 |
| Auto, backlight off, brightness minus 8 | 0 | Original minus 8 |

The camera does not expose a standard automatic exposure bias control.
Backlight compensation is an available candidate, but its effect needs measurement on this camera.
Brightness is an image adjustment. A darker image does not prove that the sensor recovered highlight detail.
The suite leaves gamma, contrast, saturation, sharpness, and anti-flicker unchanged to limit the variables.
Duplicate candidates are omitted when the original values already match them.
The suite does not select or retain a winner.

## Measurements and files

The reader uses the existing `/tmp/rgb_nv.sock` output at 1920×1080.
It limits CPU image copies to one frame per second before conversion.
It does not open a second USB capture session or add a radio video stream.
The default run measures one frame every 2 seconds and saves a JPEG every 15 seconds, starting with each block's first sample.
Images come after the camera's H.264 decoder and before the server's H.265 encoder.
They describe source image quality, not radio loss or preview encoding quality.

Results remain on the aircraft in `~/c1-daytest-results/<UTC timestamp>-<action>/`.
Fetch copies all run directories to `~/c1-daytest-results/` on the laptop by default.

| File | Contents |
|---|---|
| `state.json` | Original controls, candidates, script hash, arguments, run status, and restoration status |
| `events.jsonl` | Profile changes with UTC and elapsed time |
| `samples.csv` | Measurements, current controls, source timestamps, resource use, and image names |
| `*.jpg` | Full-resolution reference images at JPEG quality 95 |
| `controls-before.txt` | Initial controls and their flags |
| `controls-restored.txt` | Controls after restoration |
| `camera-info.txt` | Camera identity from V4L2 |

Each sample includes full-image, upper-third, and lower-half brightness, clipping, and shadow measurements.
The upper and lower regions are geometric regions. They do not identify sky or ground.
Channel clipping means any channel at or above 250. White clipping means all channels at or above 250.
Shadow pixels have luma at or below 16. Luma uses `0.299 R + 0.587 G + 0.114 B` on decoded pixels.
The CSV also includes color ratios and half-resolution Laplacian variance as a sharpness measure.
Color ratios depend on the scene. Sharpness depends on texture, motion, zoom, and noise.
Neither measure supplies a quality ranking by itself.

The shutter and gain readbacks can be inactive or stale under automatic exposure.
Treat them as reported control values, not measured exposure metadata.
Source timestamps come from the video pipeline. They are not sensor exposure times.
CPU percentage describes the test process across all cores, with one fully used core equal to 100 percent.

## Restoration and failure behavior

The suite saves the original brightness and backlight compensation before any control write.
It restores both values on completion, stop, or a handled error, then checks the readback.
The service also runs a separate restoration command after process termination, including a forced kill.
A lock prevents two suite processes from changing controls at the same time.
The service has a runtime limit and reduced CPU priority.

A missing frame, non-advancing timestamp, camera-server restart, changed automatic mode, or unexpected control value stops the comparison.
The suite records the error and attempts restoration. It does not restart the camera server.
Camera disconnection or power loss can prevent immediate restoration.
The saved state remains available for explicit recovery after the camera returns:

```bash
# On the aircraft. Replace RUN with the saved directory name.
python3 ~/.local/share/c1-daytest/c1_daytest.py restore \
  --output ~/c1-daytest-results/RUN
```

The wrapper copies the runner outside the aircraft checkout, into `~/.local/share/c1-daytest/`.
It does not deploy other repository changes, install packages, or need sudo.

## Later analysis

Compare each candidate with the neighboring baseline blocks under similar light, framing, motion, and zoom.
Use the saved images to check highlight detail and shadow loss alongside clipping percentages.
Brightness adjustments can change threshold counts without recovering detail.
Changing scenes can dominate the measurements, so do not rank candidates from whole-run averages alone.
Keep automatic exposure and white balance enabled when the final profile is chosen.

The pilot camera's `CAMERA_TUNING.md` and `tune_pilot_camera.sh` use IMX477/Argus controls.
Those controls do not apply to this C1 PRO suite.

## Software checks

```bash
python3 -m unittest discover -s remote -p test_c1_daytest.py -v
python3 -m py_compile local/c1_daytest.py remote/c1_daytest.py
```

## Ground smoke test, 2026-10-21

Nine software tests passed. The final runner completed all seven ground comparison blocks.
That run saved 18 measured frames and 13 reference images.
Automatic exposure and automatic white balance remained enabled.
The camera server kept the same process ID and restart count throughout the checks.
Normal stop and forced termination each restored the original controls.
The final preflight passed, and no test remained active.

The results are in `~/c1-daytest-results/` on the aircraft and the laptop.
The laptop's `ground-smoke-report.json` records the checks and runner hash.
Image-quality analysis remains for the flight data.
