# Candidate preparation recipe only: no simulator starts and no SITL compilation.
# No default base: supply a reviewed ubuntu:24.04@sha256:... linux/amd64 identity.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG BASE_IMAGE
RUN printf '%s\n' "$BASE_IMAGE" | grep -Eq '^ubuntu:24\.04@sha256:[0-9a-f]{64}$'
ENV DEBIAN_FRONTEND=noninteractive CMAKE_BUILD_PARALLEL_LEVEL=1 MAKEFLAGS=-j1 \
    PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git build-essential cmake ninja-build ccache \
    pkg-config python3 python3-dev python3-venv astyle file rsync unzip zip \
    libeigen3-dev libxml2-dev libssl-dev libprotobuf-dev protobuf-compiler \
    libopencv-dev libunwind-dev cppzmq-dev && rm -rf /var/lib/apt/lists/*
# Offline source recipes must carry the reviewed OSRF key. No curl-to-shell.
COPY osrf.gpg /usr/share/keyrings/osrf.gpg
RUN printf '%s\n' 'deb [arch=amd64 signed-by=/usr/share/keyrings/osrf.gpg] https://packages.osrfoundation.org/gazebo/ubuntu-stable noble main' \
    > /etc/apt/sources.list.d/gazebo.list && apt-get update && \
    apt-get install -y --no-install-recommends \
    gz-sim8-cli=8.15.0-1~noble libgz-sim8=8.15.0-1~noble \
    libgz-sim8-dev=8.15.0-1~noble && rm -rf /var/lib/apt/lists/*
# A separately reviewed source bundle must include recursively pinned submodules.
# Missing local inputs deliberately stop builds instead of downloading substitutes.
COPY PX4-Autopilot /opt/PX4-Autopilot
RUN test "$(git -C /opt/PX4-Autopilot rev-parse HEAD)" = 6ea3539157ca358c70a515878b77077af7d4611d && \
    test -z "$(git -C /opt/PX4-Autopilot status --porcelain --untracked-files=all)" && \
    git -C /opt/PX4-Autopilot submodule status --recursive > /opt/submodules.txt && \
    ! grep -Eq '^[-+U]' /opt/submodules.txt
# Exact hashed requirements/wheels must be prepared and reviewed separately.
COPY requirements.lock /opt/requirements.lock
COPY wheels /opt/wheels
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install \
    --no-index --find-links=/opt/wheels --require-hashes -r /opt/requirements.lock && \
    dpkg-query -W > /opt/packages.txt && /opt/venv/bin/pip freeze --all > /opt/python-packages.txt
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin simulation
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["/opt/venv/bin/python"]
CMD ["--version"]
