# Pilot camera tuning (IMX477, CSI)

How to change what the pilot camera (IMX477 on the CSI port, served by rcam as
`/pilot` and `/pilotl`) looks like, how to measure a change, and how to make it
stick on every aircraft. It was written after the 2026-09-28/29 purple-picture
investigation on d3, and the numbers below come from that.

## Where things live

| What | Where |
|---|---|
| Camera options (white balance, saturation, exposure) | `PILOT_CAMERA` in `remote/rtsp_config.py` |
| Resolution and frame rate, which pick the sensor mode | `PILOT_WIDTH`, `PILOT_HEIGHT`, `PILOT_FRAMERATE` in the same file |
| The server that runs them | `rcam.service` -> `remote/forked_rtsp_server.py` |
| What rcam actually started with | `journalctl -u rcam \| grep 'pilot-fork camera:'` |
| ISP tuning override and cache | `/var/nvidia/nvcam/settings/` on the drone |
| Try-and-measure helper, run from the laptop | `local/tune_pilot_camera.sh` |

The IMX477 has two modes here: mode 0 is 3840x2160 at 30 fps, which is what
rcam uses, and mode 1 is 1920x1080 at 60 fps. Always test in the mode rcam
runs, because the two do not respond to the same settings the same way.

## How a setting reaches the stream

```
edit PILOT_CAMERA on the laptop -> commit -> sync --no-build -> restart rcam on the drone -> check the journal line
```

```bash
# on the laptop
cd ~/chimera-deploy
$EDITOR remote/rtsp_config.py            # change PILOT_CAMERA
git commit -am "pilot camera: <what and why>"
sync --no-build                          # delivers to every reachable drone, no px4sim rebuild

# on each drone (sync never restarts rcam)
sudo systemctl restart rcam
journalctl -u rcam -n 80 -o cat | grep 'pilot-fork camera:'
```

The journal line is read back from the element the pipeline built, so it is
what the camera really got. Check it after every change. On 2026-09-28, commits
for wbmode=5 and wbmode=2 never reached d3 (`sync --no-build` skipped the
drones until d306694), every restart kept running wbmode=0, and it looked as if
wbmode did nothing.

Do not edit the drone's checkout to experiment. A dirty tree stops `sync` at
preflight, and it is easy to lose track of what is running. Use the
environment override below instead.

## Read-only checks

```bash
# on the drone
journalctl -u rcam -n 80 -o cat | grep 'pilot-fork camera:'    # running settings
journalctl -u nvargus-daemon -b | grep -i 'override file'       # "No override file found" = stock ISP tuning
ls -la /var/nvidia/nvcam/settings/                              # camera_overrides.isp present?
gst-inspect-1.0 nvarguscamerasrc                                # every option, range and default
```

To check for an IR-cut filter, point a TV remote at the camera and press a
button. A bright flash in the stream means the lens passes infrared. The lens
part number says the same thing: `...M12A650` has a 650 nm IR-cut filter and
`...ANIR` has none. d3 flashes, so d3 has no IR-cut filter.

## Tuning loop

Score each try with a grey card and some plants in view. The targets are:

- R/G and B/G on the grey card within about 5% of 1.00
- the brightest white at 235 or more, with less than 0.5% of pixels clipped
- plants that look green

Get the colour right first. Change exposure only after that, and only if a
measurement shows it helps.

### With the helper (from the laptop)

```bash
cd ~/chimera-deploy
# one or more candidates, each "label|nvarguscamerasrc options"; asks for the drone's sudo password once
./local/tune_pilot_camera.sh \
  'current|wbmode=1 saturation=0.6 exposurecompensation=1.25 exposuretimerange="13000 16666666"' \
  'brighter|wbmode=1 saturation=0.6 exposurecompensation=1.5 exposuretimerange="13000 16666666"'

./local/tune_pilot_camera.sh -d 10.200.142.61 'd1-auto|wbmode=1'   # another drone
./local/tune_pilot_camera.sh --measure                             # measure without changing anything
./local/tune_pilot_camera.sh --reset                               # drop the override, back to the committed PILOT_CAMERA
```

For each candidate the helper sets `PILOT_CAMERA` in the drone's systemd
environment, restarts rcam, prints the `pilot-fork camera:` line, waits for
auto exposure to settle, grabs one frame of `/pilot` on the laptop, and prints:

```
== manual-green: wbmode=9 saturation=0.6
   pilot-fork camera: wbmode=manual saturation=0.6 awblock=False aelock=False exposuretimerange=None ...
   R/G=0.68 B/G=0.57 | meanY=93 white(p99.5)=254 clipped=25.34% | /tmp/pilot_tune/manual-green.jpg
Still overriding. Keep a winner by committing it as PILOT_CAMERA, then run --reset.
```

R/G and B/G are for the whole frame, so they only stand in for the grey card
when the scene is mostly neutral. Crop to the card (see below) for a real
score. It needs `ffmpeg`, `python3-numpy` and `python3-pil` on the laptop.

The override lives only in the drone's systemd environment. Git and `sync`
cannot see it, and a reboot clears it. When a setting wins, commit it as
`PILOT_CAMERA` and run `--reset`.

### By hand (what the helper does)

```bash
# on the drone: try options without touching git
sudo systemctl set-environment 'PILOT_CAMERA=wbmode=1 saturation=0.6 exposurecompensation=1.25'
sudo systemctl restart rcam
journalctl -u rcam -n 80 -o cat | grep 'pilot-fork camera:'
sudo systemctl unset-environment PILOT_CAMERA && sudo systemctl restart rcam   # undo

# on the laptop: grab a frame and score a grey card at pixels x0,y0-x1,y1 (of the 960x540 frame)
ffmpeg -loglevel error -rtsp_transport tcp -i rtsp://10.200.142.63:8554/pilot -frames:v 1 -vf scale=960:540 -y /tmp/f.jpg
python3 -c "
import numpy as np; from PIL import Image
a = np.asarray(Image.open('/tmp/f.jpg').convert('RGB')).astype(float)
x0, y0, x1, y1 = 400, 200, 480, 280          # the grey card
r, g, b = a[y0:y1, x0:x1].reshape(-1, 3).mean(0)
y = 0.299*a[..., 0] + 0.587*a[..., 1] + 0.114*a[..., 2]
print(f'card R/G={r/g:.2f} B/G={b/g:.2f}  white={np.percentile(y, 99.5):.0f}  clipped={(a >= 250).any(2).mean()*100:.2f}%')"
```

### An aircraft that needs different settings

The committed `PILOT_CAMERA` suits d3's lens, which has no IR-cut filter. An
aircraft with an IR-cut lens wants `saturation` back at 1.0. To give one
aircraft its own options without forking the repo, set a persistent override on
that drone:

```bash
sudo systemctl edit rcam
#   [Service]
#   Environment="PILOT_CAMERA=wbmode=1 exposuretimerange=\"13000 16666666\""
sudo systemctl restart rcam
```

That override is outside git. `sync` does not carry it or check it, so write
down which aircraft have one. `systemctl cat rcam` shows it.

## The options

Ranges and defaults are from `gst-inspect-1.0 nvarguscamerasrc` on JetPack
r36.4.4. Put the options in `PILOT_CAMERA` separated by spaces, and quote any
value that contains a space.

| Option | Range (default) | What it does | Suggested |
|---|---|---|---|
| `wbmode` | 0 off, **1 auto**, 2 incandescent, 3 fluorescent, 4 warm-fluorescent, 5 daylight, 6 cloudy-daylight, 7 twilight, 8 shade, 9 manual | White balance | `1`. On d3 every preset was further from neutral than auto. `9` turns the picture green, and `0` looked just like auto |
| `saturation` | 0 to 2 (**1**) | Colour intensity | `0.6` on a lens without IR-cut, `1.0` with IR-cut. Never raise it, because it amplifies the magenta |
| `exposurecompensation` | -2 to 2 EV (**0**) | Brightness that auto exposure aims for | `+1.25` got d3's whites to 232 in a dim room. Re-check outdoors, where it may clip the sky. `+1.5` clipped 18% indoors |
| `exposuretimerange` | `"low high"` in ns (sensor 13000 to 683709000; 30 fps caps it at ~33 ms) | Limits on shutter time | `"13000 16666666"` (1/60 s) bounds motion blur. Keep the cap a multiple of 8333333 ns (1/120 s) so 60 Hz lamps do not band |
| `gainrange` | `"low high"` (sensor 1 to 22.25) | Analog gain limits | Leave it. A lower top value means less noise but a darker picture in low light |
| `ispdigitalgainrange` | `"low high"` | Digital gain limits | Leave it. A lower top value means less amplified noise |
| `aeantibanding` | 0 off, **1 auto**, 2 50 Hz, 3 60 Hz | Avoids flicker from mains lighting | `1` or `3` in the US. `0`, as on the old trial branch, can band under lamps |
| `aelock`, `awblock` | true/false (**false**) | Freeze exposure or white balance where they are | Handy for repeatable test frames. Converge on the grey card, then lock |
| `aeregion` | `"left top right bottom weight"` (null) | Meter exposure on part of the frame | For example, meter the lower part of the frame so the sky does not darken the ground |
| `tnr-mode`, `tnr-strength` | 0 off, **1 fast**, 2 high quality; -1 to 1 (**-1**) | Temporal noise reduction | Leave it. More strength smears moving things |
| `ee-mode`, `ee-strength` | 0 off, **1 fast**, 2 high quality; -1 to 1 (**-1**) | Edge sharpening | Leave it. More strength adds halos |
| `sensor-mode` | -1 auto, 0, 1 (**-1**) | Force a sensor mode | Leave it on auto. `PILOT_WIDTH`/`HEIGHT`/`FRAMERATE` select mode 0 |

## Results on d3, 2026-09-29

Measured through rcam, whole frame, warm indoor light at night, with no IR-cut
filter and stock ISP tuning:

| Options | R/G | B/G | White | Clipped |
|---|---|---|---|---|
| `wbmode=1` (auto, the old default) | 1.37 | 1.37 | 160 | 0.00% |
| `wbmode=3` fluorescent | 1.77 | 1.11 | 147 | 0.00% |
| `wbmode=4` warm-fluorescent | 1.43 | 1.49 | 157 | 0.00% |
| `wbmode=5` daylight | 1.93 | 0.71 | 139 | 0.00% |
| feature/pilot-cam-tuning trial (EV -1, 8 ms cap, antibanding off) | 1.53 | 1.52 | 107 | 0.00% |
| `saturation=0.8 exposurecompensation=1.0` | 1.24 | 1.24 | 219 | 0.28% |
| **`saturation=0.6 exposurecompensation=1.25`, 1/60 s cap (committed)** | **1.17** | **1.16** | **232** | **0.17%** |
| `saturation=0.7 exposurecompensation=1.25`, 1/60 s cap | 1.21 | 1.20 | 232 | 1.94% |
| `saturation=0.7 exposurecompensation=1.5`, 1/60 s cap | 1.19 | 1.17 | 250 | 18.05% |

All of those frames are the same view of a couch. Later the committed
settings, pointed at a dim wall next to a brightly lit doorway, clipped 27%
of the frame. EV +1.25 suits a flat, dim scene. Check it on the real one,
outdoors, before flight.

These settings soften the purple; they cannot remove it. That takes one of the
fixes below.

## Fixing it properly

### 1. An IR-cut filter

The infrared that the lens passes lands mostly in the red and blue channels,
and the ISP expects it to have been filtered out. Fit a lens with a 650 nm
IR-cut filter (`...M12A650`), or an M12 IR-cut filter. Then re-tune:
`saturation` should go back to 1.0 and exposure compensation toward 0 to +0.5.

### 2. An ISP tuning file

The best source is EchoMAV's tuning file for this module. The fallback is
RidgeRun's IMX477 file, but it was made for the Raspberry Pi HQ camera with a
different lens, so the lens shading may be off. Whether JetPack r36.4.4 still
reads the file is unknown. Test on the ground, on one drone:

```bash
B=/var/nvidia/nvcam/settings.bak-$(date +%F); sudo mkdir -p $B
sudo systemctl stop rcam
sudo mv /var/nvidia/nvcam/settings/nvcam_cache_* /var/nvidia/nvcam/settings/serial_no_* $B/ 2>/dev/null
sudo install -o root -g root -m 664 camera_overrides.isp /var/nvidia/nvcam/settings/
sudo systemctl restart nvargus-daemon && sudo systemctl start rcam
journalctl -u nvargus-daemon -b | grep -i override     # did it load?
```

To undo it, remove `camera_overrides.isp`, move the cache files back from `$B`,
then restart nvargus-daemon and rcam. The file lives outside git, so `sync`
will not deploy it or notice it. Record which aircraft have one.

### 3. A stopgap in software

Apply a fixed linear gain (about R / 1.46, B / 1.75) to a copy of the image,
such as the casualty crop, and leave the camera output alone. Measure the
gains again on a grey card first. Near-white highlights turn slightly green.

## Pitfalls

- Never restart `nvargus-daemon` while rcam is running. rcam crashes (SEGV),
  systemd restarts it 5 s later, and it fights your test for the sensor. Stop
  rcam first and start it again afterwards.
- Only one Argus client can hold the sensor. `Failed to create CaptureSession`
  means something else has it.
- Test at 3840x2160 and 30 fps, the mode rcam runs, not 1080p60.
- `wbmode=0` is not neutral. In mode 0 it looks just like auto.
- `sync` switches every drone to the laptop's branch. Use `sync --branch NAME`
  to test a branch on the drones.
- `sync` never restarts rcam, and `sync --no-build` still delivers commits
  (since d306694).
- Overrides from `systemctl set-environment`, from `systemctl edit rcam`, and
  in `camera_overrides.isp` are all invisible to git and `sync`. Commit what
  should be the same everywhere.
