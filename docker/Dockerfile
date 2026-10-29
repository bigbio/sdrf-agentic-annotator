# pi runner image plus the sdrf-skills bundle and its command-line tools (sdrf-tools, parse_sdrf)
ARG SDRF_SKILLS_IMAGE=ghcr.io/bigbio/sdrf-skills:sha-1ea3d2f
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.0

# The sdrf-skills Python needs glibc 2.38, but the pi image (bookworm) has 2.36. So take the bundle,
# the ontology cache and the package versions from it, and install them on a portable uv Python.
FROM ${SDRF_SKILLS_IMAGE} AS sdrf-skills
RUN pip freeze --exclude-editable > /tmp/constraints.txt \
    && python -c 'import platform; print(platform.python_version())' > /tmp/python-version

FROM ${UV_IMAGE} AS uv

FROM public.cr.seqera.io/nextflow/nf-agent-pi:0.6.0

# safe.directory: the review gate runs git on repositories owned by another uid.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates jq \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

# `find /` blocks for hours on a cluster filesystem (GPFS/NFS) and stalls the agent task, so the
# guard refuses it; /usr/local/bin comes before /usr/bin in PATH.
COPY find-guard.sh /usr/local/bin/find
RUN chmod 0755 /usr/local/bin/find && [ "$(command -v find)" = /usr/local/bin/find ] \
    && ! find / -maxdepth 0 2>/dev/null

COPY --from=uv /uv /usr/local/bin/uv
COPY --from=sdrf-skills /opt/sdrf-skills /opt/sdrf-skills
COPY --from=sdrf-skills /opt/cache /opt/cache
# The PRIDE ontology cache of sdrf-pipelines lacks the terms added to the PRIDE ontology since it was built: `study sample`, `control sample`,
# `calibration sample` and `blank` (sample types, PRIDE:0001013 to PRIDE:0001016), so parse_sdrf rejects them. This copy is that cache plus the 21 missing terms.
COPY pride.parquet /opt/cache/sdrf-pipelines/ontologies/pride.parquet
COPY --from=sdrf-skills /tmp/constraints.txt /tmp/python-version /tmp/

# Editable install: the tools find spec/ and data/ relative to their own files.
RUN chmod 1777 /opt/cache \
    && UV_PYTHON_INSTALL_DIR=/opt/python uv venv --no-cache --python "$(cat /tmp/python-version)" /opt/venv \
    && uv pip install --no-cache --python /opt/venv/bin/python -c /tmp/constraints.txt -e /opt/sdrf-skills \
    && rm /tmp/constraints.txt /tmp/python-version /usr/local/bin/uv

# The module skills still resolve bundle paths from CLAUDE_PLUGIN_ROOT; SDRF_SKILLS_ROOT is the primary root.
ENV PATH=/opt/venv/bin:$PATH \
    SDRF_SKILLS_ROOT=/opt/sdrf-skills \
    CLAUDE_PLUGIN_ROOT=/opt/sdrf-skills \
    XDG_CACHE_HOME=/opt/cache \
    PYTHONDONTWRITEBYTECODE=1
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
