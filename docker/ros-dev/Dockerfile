FROM ros:humble-ros-base-jammy

ENV DEBIAN_FRONTEND=noninteractive

# ROS/dev tools, MAVROS, GStreamer/video tools, VAAPI, Foxglove, and known rosdep dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash-completion \
    build-essential \
    curl \
    ffmpeg \
    git \
    gstreamer1.0-gl \
    gstreamer1.0-libav \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-base-apps \
    gstreamer1.0-plugins-good \
    gstreamer1.0-tools \
    gstreamer1.0-vaapi \
    gstreamer1.0-x \
    intel-media-va-driver \
    iputils-ping \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libva-drm2 \
    libva-x11-2 \
    mesa-va-drivers \
    nano \
    net-tools \
    netcat-openbsd \
    openssh-client \
    python3-colcon-common-extensions \
    python3-gi \
    python3-gst-1.0 \
    python3-pip \
    python3-rosdep \
    python3-vcstool \
    qtbase5-dev \
    ros-humble-cv-bridge \
    ros-humble-domain-bridge \
    ros-humble-foxglove-bridge \
    ros-humble-image-transport \
    ros-humble-mavros \
    ros-humble-mavros-extras \
    ros-humble-network-bridge \
    ros-humble-qt-gui-cpp \
    ros-humble-rqt-gui \
    ros-humble-rqt-gui-cpp \
    ros-humble-vision-msgs \
    sudo \
    tmux \
    v4l-utils \
    vainfo \
    vim \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install rosdep dependencies declared by workspace package manifests.
# docker/rosdep_src is generated from ros2_ws/src package.xml files only,
# so normal source edits do not invalidate this expensive layer.
COPY docker/rosdep_src /tmp/ros2_ws/src
RUN rosdep update && \
    apt-get update && \
    rosdep install --from-paths /tmp/ros2_ws/src \
      --ignore-src \
      --rosdistro humble \
      -y && \
    rm -rf /var/lib/apt/lists/* /tmp/ros2_ws

# MAVROS requires GeographicLib datasets.
RUN /opt/ros/humble/lib/mavros/install_geographiclib_datasets.sh

# Python packages not available through standard rosdep/apt.
# Pin NumPy below 2 because ROS Humble cv_bridge/scipy are built against NumPy 1.x.
RUN python3 -m pip install --no-cache-dir \
    "numpy==1.24.4" \
    "ultralytics" \
    "folium"

# Create a normal dev user.
ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000
ARG RENDER_GID=110

RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && groupadd --gid ${RENDER_GID} render \
    && useradd --uid ${USER_UID} --gid ${USER_GID} -G render -m ${USERNAME} -s /bin/bash \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME}

COPY docker/ros-dev/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY --chown=dev:dev local/.bash_aliases /home/dev/.bash_aliases
COPY --chown=dev:dev docker/chimera-deploy /home/dev/chimera-deploy

USER dev
WORKDIR /home/dev/ros2_ws

RUN echo 'source /opt/ros/humble/setup.bash' >> /home/dev/.bashrc
COPY --chown=dev:dev docker/.bashrc /home/dev/.bashrc

ENTRYPOINT ["/entrypoint.sh"]
