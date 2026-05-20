FROM ros:humble-ros-base-jammy

ENV DEBIAN_FRONTEND=noninteractive

# ROS/dev tools, MAVROS, GStreamer/video tools, and known rosdep dependencies
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
    gstreamer1.0-plugins-good \
    gstreamer1.0-tools \
    gstreamer1.0-x \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    nano \
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
    vim \
    wget \
    && rm -rf /var/lib/apt/lists/*


# Install rosdep dependencies declared by workspace packages at image build time
COPY ros2_ws/src /tmp/ros2_ws/src
RUN rosdep update && \
    apt-get update && \
    rosdep install --from-paths /tmp/ros2_ws/src \
      --ignore-src \
      --rosdistro humble \
      -y && \
    rm -rf /var/lib/apt/lists/* /tmp/ros2_ws

# MAVROS requires GeographicLib datasets
RUN /opt/ros/humble/lib/mavros/install_geographiclib_datasets.sh

# Create a normal dev user
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

USER dev
WORKDIR /home/dev/ros2_ws

# Source ROS automatically in interactive shells too
RUN echo 'source /opt/ros/humble/setup.bash' >> /home/dev/.bashrc

ENTRYPOINT ["/entrypoint.sh"]


# Python packages not available through standard rosdep/apt.
# Pin NumPy below 2 because ROS Humble cv_bridge/scipy are built against NumPy 1.x.
RUN python3 -m pip install --no-cache-dir \
    "numpy==1.24.4" \
    "ultralytics" \
    "folium"

# User shell aliases
COPY --chown=dev:dev local/.bash_aliases /home/dev/.bash_aliases

# Feature layer: Foxglove Bridge for ROS 2
RUN sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    ros-humble-foxglove-bridge \
    && sudo rm -rf /var/lib/apt/lists/*

# Project helper files
COPY --chown=dev:dev docker/chimera-deploy /home/dev/chimera-deploy

# Feature layer: minimal network diagnostics
RUN sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    iputils-ping \
    net-tools \
    netcat-openbsd \
    && sudo rm -rf /var/lib/apt/lists/*

# Feature layer: VAAPI hardware video decode support
RUN sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    gstreamer1.0-vaapi \
    vainfo \
    libva-drm2 \
    libva-x11-2 \
    mesa-va-drivers \
    intel-media-va-driver \
    && sudo rm -rf /var/lib/apt/lists/*

# Feature layer: VAAPI hardware video decode support
RUN sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    gstreamer1.0-vaapi \
    vainfo \
    libva-drm2 \
    libva-x11-2 \
    mesa-va-drivers \
    intel-media-va-driver \
    && sudo rm -rf /var/lib/apt/lists/*
