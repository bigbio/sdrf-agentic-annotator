# pi runner image plus the sdrf-skills command-line tools (sdrf-tools, parse_sdrf); techsdrf is left out because its wheel build fails
FROM public.cr.seqera.io/nextflow/nf-agent-pi:0.6.0

ARG SDRF_SKILLS_REF=0fb449f3c7ba6ed5820df062910463c4253ed254

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
