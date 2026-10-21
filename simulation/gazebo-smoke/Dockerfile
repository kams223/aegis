# Preparation recipe; missing authenticated archive bundle deliberately fails.
FROM ubuntu:24.04@sha256:a2d43bffc46670d7108bb3c0468c67c5557c4c92e83e1e34cbff1322ad1b94dc
ARG INPUTS_SHA256
ARG WORLD_SHA256
LABEL org.aegis.smoke.inputs-sha256=$INPUTS_SHA256 \
      org.aegis.smoke.world-sha256=$WORLD_SHA256 \
      org.aegis.smoke.gazebo-version=8.15.0
COPY smoke.py launch.py profile.json inputs.json gravity.sdf /opt/smoke/
# The host verifier must authenticate and checksum the complete .deb closure first.
# No APT repository access, fallback download, PX4 sources, compiler or pip inputs.
RUN --network=none --mount=type=bind,source=artifacts,target=/inputs/artifacts,readonly \
    test -n "$INPUTS_SHA256" && test -n "$WORLD_SHA256" && \
    printf '%s  /opt/smoke/inputs.json\n%s  /opt/smoke/gravity.sdf\n' "$INPUTS_SHA256" "$WORLD_SHA256" | sha256sum --check --strict && \
    cd /inputs/artifacts && sha256sum --check --strict SHA256SUMS && \
    awk '{print $2}' SHA256SUMS | LC_ALL=C sort > /tmp/expected-debs && \
    find debs -maxdepth 1 -type f -printf '%p\n' | LC_ALL=C sort > /tmp/actual-debs && \
    cmp /tmp/expected-debs /tmp/actual-debs && \
    DEBIAN_FRONTEND=noninteractive apt-get --no-download --no-install-recommends -y install /inputs/artifacts/debs/*.deb && \
    python3 -B /opt/smoke/smoke.py --verify-bundle /inputs/artifacts && \
    python3 -B /opt/smoke/smoke.py --verify-installed && \
    dpkg-query -W > /opt/smoke/installed-packages.txt && \
    python3 -B -c 'import hashlib,json,pathlib; p=pathlib.Path("/opt/smoke"); (p/"build-receipt.json").write_text(json.dumps({"inputs_sha256":hashlib.sha256((p/"inputs.json").read_bytes()).hexdigest(),"gazebo_version":"8.15.0"})+"\n")' && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /tmp/expected-debs /tmp/actual-debs
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin simulation
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/work GZ_IP=127.0.0.1 GZ_SIM_RESOURCE_PATH=/opt/smoke
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["python3", "-B", "/opt/smoke/smoke.py"]
# Explicit launch is required; default reports preparation status only.
CMD []
