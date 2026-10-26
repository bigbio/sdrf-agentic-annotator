# pi runner image plus the sdrf-skills command-line tools (sdrf-tools, parse_sdrf); techsdrf is left out because its wheel build fails
FROM public.cr.seqera.io/nextflow/nf-agent-pi:0.6.0

# Pin sdrf-skills to a ref that contains the curated uveal-melanoma cell-line DB
# additions (UPMD-2/UPMM-2/UPMM-3/92-1) from bigbio/sdrf-skills PR #126.
# 0fb449f (previous pin) lacked these curated rows, so the offline
# `sdrf-tools cellline lookup` could not resolve those real Cellosaurus lines.
ARG SDRF_SKILLS_REF=ebf95fb3a36a1a81437a26472b14df3ecfa22924

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates jq \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/bigbio/sdrf-skills /opt/sdrf-skills \
    && cd /opt/sdrf-skills \
    && git checkout --quiet ${SDRF_SKILLS_REF} \
    && git submodule update --init --recursive --depth 1 \
    && rm -rf .git

WORKDIR /opt/sdrf-skills
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH=/opt/venv/bin:$PATH \
    CLAUDE_PLUGIN_ROOT=/opt/sdrf-skills \
    SDRF_SKILLS_ROOT=/opt/sdrf-skills
WORKDIR /opt/nf-agent-pi
ENTRYPOINT []

# This image is published to ghcr.io/bigbio/sdrf-agentic-annotator by
# .github/workflows/docker.yml (it pushes to ghcr.io/<repo>, i.e. this repo's
# path). Any change under docker/ re-triggers that workflow on merge and
# re-publishes the `dev` / semver tags there. Update this label if you move it.
LABEL org.opencontainers.image.title="bigbio/sdrf-agentic-annotator runner image" \
      org.opencontainers.image.source="https://github.com/bigbio/sdrf-agentic-annotator"

# pi resolves extra OpenAI-compatible providers from $PI_CODING_AGENT_DIR/models.json.
# The agent task runs as an arbitrary non-root uid (Nextflow `-u $(id -u):$(id -g)`), and the
# image HOME (`/`) is not writable, so we provide a config dir and point PI_CODING_AGENT_DIR at it.
# The baked models.json here is only a credential-free TEMPLATE (empty providers): users register
# their own OpenAI-compatible gateway at run time with `--models_json`, which the docker profile
# bind-mounts over /opt/pi-config/models.json. pi also writes models-store.json beside models.json,
# hence 0777 on the dir.
RUN mkdir -p /opt/pi-config && chmod 0777 /opt/pi-config
COPY models.json /opt/pi-config/models.json
ENV PI_CODING_AGENT_DIR=/opt/pi-config
