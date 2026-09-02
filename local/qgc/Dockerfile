# QGroundControl runtime for hosts older than the AppImage's build platform.
#
# The v5.1+ AppImages are built against glibc 2.38 (Ubuntu 24.04). On Ubuntu
# 22.04 (glibc 2.35) they abort at startup with a wall of "version GLIBC_2.38
# not found". This image supplies the newer runtime and nothing else: the
# AppImage is extracted at build time (a container cannot use FUSE without
# extra privileges) and every piece of state lives on a bind mount from the
# host, so settings, flight logs and map tiles are the same files a native
# install would use.
#
# quickstart.sh builds this only when the host is too old to run the AppImage
# directly, and passes the downloaded AppImage in as the build context.

FROM ubuntu:24.04

ARG HOST_UID=1000
ARG HOST_GID=1000
ARG HOST_USER=user

# The release to install. The image fetches it from GitHub Releases itself, so
# `docker build` alone rebuilds everything from nothing - no binary in the repo
# and no prior download needed. quickstart.sh passes a copy it already has in
# the build context to save the round trip; either way the checksum is checked.
ARG QGC_VERSION=5.1.4
ARG QGC_ARCH=x86_64
ARG QGC_SHA256=1c4ac089abfaac6c6fcd75c7b477ea18da1bc3592cddca5ab1a19c1a13410e65

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      libfontconfig1 libfreetype6 \
      libx11-6 libx11-xcb1 libxext6 libxfixes3 libxi6 libxrender1 \
      libxcb1 libxcb-glx0 libxcb-keysyms1 libxcb-image0 libxcb-shm0 \
      libxcb-icccm4 libxcb-sync1 libxcb-xfixes0 libxcb-shape0 libxcb-randr0 \
      libxcb-render-util0 libxcb-util1 libxcb-xinerama0 libxcb-xkb1 \
      libxcb-cursor0 libxkbcommon0 libxkbcommon-x11-0 \
      libgl1 libglx0 libegl1 libglvnd0 libopengl0 libvulkan1 libgbm1 \
      libglib2.0-0t64 libdbus-1-3 libnss3 \
      libasound2t64 libpulse0 libudev1 libusb-1.0-0 libsdl2-2.0-0 \
      libspeechd2 libssl3t64 libsm6 libice6 \
      libwayland-client0 libwayland-cursor0 libwayland-egl1 \
      libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
      gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
      gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
      gstreamer1.0-x gstreamer1.0-gl \
      libdrm2 \
      fonts-dejavu-core \
      curl \
    && rm -rf /var/lib/apt/lists/*

# An empty directory in the context is normal and means "fetch it". Docker has
# no conditional COPY, so the choice is made in the RUN below rather than here.
COPY appimage/ /tmp/appimage/

RUN set -eux; \
    f="/tmp/appimage/QGroundControl-${QGC_ARCH}.AppImage"; \
    if [ ! -f "$f" ]; then \
        echo "Fetching QGroundControl ${QGC_VERSION} (${QGC_ARCH}) from GitHub Releases"; \
        curl -fL --retry 3 -o "$f" \
          "https://github.com/mavlink/qgroundcontrol/releases/download/v${QGC_VERSION}/QGroundControl-${QGC_ARCH}.AppImage"; \
    else \
        echo "Using the copy supplied in the build context"; \
    fi; \
    if [ -n "${QGC_SHA256}" ]; then echo "${QGC_SHA256}  $f" | sha256sum -c -; fi; \
    chmod +x "$f"; \
    cd /opt && "$f" --appimage-extract >/dev/null; \
    mv /opt/squashfs-root /opt/qgc; \
    rm -rf /tmp/appimage

# The in-container user must match the host UID/GID, or the bind-mounted
# settings directory is unwritable and QGroundControl silently loses every
# change. ubuntu:24.04 ships its own uid-1000 "ubuntu" user; take the id back.
RUN if getent passwd ${HOST_UID} >/dev/null; then \
      userdel -rf "$(getent passwd ${HOST_UID} | cut -d: -f1)" || true; \
    fi \
    && if getent group ${HOST_GID} >/dev/null; then \
         groupmod -n ${HOST_USER} "$(getent group ${HOST_GID} | cut -d: -f1)"; \
       else groupadd -g ${HOST_GID} ${HOST_USER}; fi \
    && useradd -M -u ${HOST_UID} -g ${HOST_GID} -d /home/${HOST_USER} \
         -s /bin/bash ${HOST_USER} \
    && install -d -o ${HOST_UID} -g ${HOST_GID} \
         /home/${HOST_USER}/.config /home/${HOST_USER}/.cache \
         /home/${HOST_USER}/Documents/QGroundControl \
    # Serial radios and USB telemetry arrive through the dialout group.
    && usermod -aG dialout ${HOST_USER}

USER ${HOST_UID}:${HOST_GID}
WORKDIR /home/${HOST_USER}

ENV QT_X11_NO_MITSHM=1

ENTRYPOINT ["/opt/qgc/AppRun"]
