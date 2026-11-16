# Build and serve the Specter DIY browser simulator in a container.
#
#   docker build -t specter-sim .
#   docker run --rm -p 127.0.0.1:8765:8765 specter-sim
#
# then open http://localhost:8765/. The first stage only wraps run-local.sh, so
# the build logic stays in web/browser/build-browser.sh. It downloads the
# firmware and Emscripten and takes several minutes. The second stage keeps just
# the tracked site files plus the generated build and a Python web server (no
# .git, no tests or tools, no untracked files), so the final image is small and
# `docker run` starts immediately. The build stage itself needs several GB of
# disk in Docker's build cache (`docker builder prune` frees it afterwards).
#
# Build argument: SPECTER_REF=<tag|branch|sha> simulates another firmware
# revision. Simulator provenance is read from the .git directory that is copied
# into the image, so build from a git clone, not from a ZIP download.

# Both stages use the same base image, pinned by digest. Update it deliberately:
# docker pull ubuntu:24.04, then copy the new digest.
ARG BASE=ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

FROM ${BASE} AS build
RUN apt-get update \
 && apt-get install --yes --no-install-recommends \
      git python3 build-essential pkg-config libffi-dev libreadline-dev \
      ca-certificates xz-utils \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --shell /bin/bash sim
RUN install -d --owner=sim --group=sim /home/sim/specter-diy-web-simulator
USER sim
WORKDIR /home/sim/specter-diy-web-simulator
COPY --chown=sim:sim . .
ARG SPECTER_REF=
RUN SPECTER_REF="$SPECTER_REF" BUILD_ONLY=1 ./run-local.sh \
 && mkdir /tmp/site \
 && git ls-files -z -- web/index.html web/assets 'web/browser/*.js' \
      | xargs -0 cp --parents -t /tmp/site \
 && cp --parents -r web/builds web/browser/current.json /tmp/site

FROM ${BASE}
RUN apt-get update \
 && apt-get install --yes --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/*
USER ubuntu
WORKDIR /site
COPY --from=build /tmp/site/web ./web
EXPOSE 8765
CMD ["python3", "-m", "http.server", "8765", "--bind", "0.0.0.0", "--directory", "web"]
