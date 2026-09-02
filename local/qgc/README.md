# QGroundControl

One command, from a clean machine to a launchable app:

```bash
./local/qgc/quickstart.sh
```

It is safe to run again at any time. It will not overwrite settings you already
have unless you ask it to.

## What it does

1. Downloads the pinned QGroundControl release from GitHub Releases and checks
   it against a recorded SHA-256. No binary is committed to this repo; the
   download is cached in `.cache/` so it happens once.
2. Works out whether this host can run that build directly, and installs it
   either natively or inside a minimal container (see below).
3. Installs the host packages QGroundControl needs, adds you to `dialout` for
   USB radios, and masks ModemManager, which otherwise grabs a Pixhawk and
   probes it as a modem. This is the only part that needs `sudo`; skip it with
   `--no-apt`.
4. Seeds `~/.config/QGroundControl/QGroundControl.ini` from
   [`QGroundControl.ini`](QGroundControl.ini) in this directory **only if you do
   not already have one**.
5. Registers a desktop entry named `QGC <version>` with the release's own icon,
   and reloads the launcher so it appears without logging out.

Afterwards: search your apps for **QGC 5.1.4**, or run `qgroundcontrol`.

## Native or containerised

The AppImage bundles its own Qt but still links the host's glibc. The v5.1
releases are built on Ubuntu 24.04 and need glibc 2.38, so on Ubuntu 22.04
(glibc 2.35) they abort at startup with a wall of `version GLIBC_2.38 not
found`.

`quickstart.sh` reads what the AppImage actually demands and compares it to the
host, rather than guessing from the distro version:

- **Host new enough** — the AppImage is installed to `~/.local/bin/` and run
  directly.
- **Host too old** — [`Dockerfile`](Dockerfile) builds a small `ubuntu:24.04`
  image that supplies the newer runtime and nothing else, and
  [`launcher.sh`](launcher.sh) is installed in its place.

The container keeps no state. Settings, flight logs, the map tile cache, the
network stack and `/dev` are all bind-mounted from the host, so a native and a
containerised QGroundControl on the same machine share one settings file. X11,
the NVIDIA GPU, PulseAudio and speech-dispatcher are passed through, so the
map, video, alert tones and spoken warnings behave as they do natively.

Force either path with `--mode native` or `--mode container`.

## Rebuilding

Nothing here is precious. Any of it can be thrown away and remade.

| Want | Command |
| --- | --- |
| Rebuild the container image | `./local/qgc/quickstart.sh --rebuild` |
| Re-download the release | `./local/qgc/quickstart.sh --refetch` |
| Remove app, icon, entry, image and download | `./local/qgc/quickstart.sh --uninstall` |
| Rebuild everything from nothing | `./local/qgc/quickstart.sh --uninstall && ./local/qgc/quickstart.sh` |

`--rebuild` passes `--pull --no-cache`, so the base image is re-pulled and every
layer is rebuilt. `--uninstall` never touches your settings.

The image can also be built entirely on its own - no cached download, nothing
from this script, no binary in the repo. The Dockerfile fetches the release
from GitHub Releases and verifies it:

```bash
docker build -f local/qgc/Dockerfile -t qgc:5.1.4 local/qgc
```

It takes the release as build arguments, so it can build any version without
editing anything:

```bash
docker build -f local/qgc/Dockerfile -t qgc:5.1.5 local/qgc \
  --build-arg QGC_VERSION=5.1.5 \
  --build-arg QGC_SHA256=<sha256 of the release asset>
```

Pass an empty `QGC_SHA256` to skip the check. `quickstart.sh` hands the build a
copy it already downloaded, when it has one, so the same 190MB is not fetched
twice; with an empty `appimage/` directory the Dockerfile fetches it instead.
The AppImage is downloaded, unpacked and deleted inside a single layer, so it
does not sit in the image adding 190MB to it.

## Settings

[`QGroundControl.ini`](QGroundControl.ini) is the flight-tested configuration:
comm links, the map provider and offline tile server, video source, telemetry
bar layout and units. `@HOME@` in it is replaced with your home directory at
install time; nothing else in it is machine-specific.

To adopt it on a machine that already has settings:

```bash
./local/qgc/quickstart.sh --force-settings   # your old ini is backed up first
```

To push a change you made in the app back into the repo:

```bash
sed "s|$HOME/|@HOME@/|g" ~/.config/QGroundControl/QGroundControl.ini \
    > local/qgc/QGroundControl.ini
```

## Upgrading the pinned release

Get the digests for the new tag:

```bash
curl -s https://api.github.com/repos/mavlink/qgroundcontrol/releases/tags/vX.Y.Z \
  | python3 -c 'import json,sys;[print(a["name"],a.get("digest")) for a in json.load(sys.stdin)["assets"]]'
```

Update `QGC_VERSION`, `SHA256_x86_64` and `SHA256_aarch64` at the top of
`quickstart.sh` and the `QGC_VERSION`/`QGC_SHA256` defaults in the `Dockerfile`,
then re-run the script. Each version installs as its own binary, icon and
desktop entry, so the previous one stays where it is and you can fall back by
launching it from the app grid.

To try a release without editing the pin — which skips the checksum, since the
recorded one will not match:

```bash
./local/qgc/quickstart.sh --version 5.1.5
```

## Options

| Flag | Effect |
| --- | --- |
| `--version X.Y.Z` | install this release instead of the pinned one |
| `--mode native\|container` | override the glibc autodetection |
| `--force-settings` | replace your ini with this repo's defaults (backs up first) |
| `--no-apt` | skip the host package step, the only part needing sudo |
| `--rebuild` | rebuild the container image from scratch (`--pull --no-cache`) |
| `--refetch` | discard the cached download and fetch the release again |
| `--uninstall` | remove this version's app, icon, entry, image and download |

## Layout

| File | |
| --- | --- |
| `quickstart.sh` | the one command |
| `QGroundControl.ini` | default settings, `@HOME@`-templated |
| `Dockerfile` | 24.04 runtime, built only when the host is too old; fetches the release itself |
| `appimage/` | optional build-context drop point; empty means "fetch it" |
| `launcher.sh` | installed in place of the AppImage in container mode |
| `qgroundcontrol.png` | icon fallback for a build shipping neither SVG nor PNG |
| `.cache/` | downloaded AppImages, git-ignored |
| `.dockerignore` | keeps the cache out of a hand-run build context |
