# pi runner image plus the sdrf-skills command-line tools (sdrf-tools, parse_sdrf); techsdrf is left out because its wheel build fails
FROM public.cr.seqera.io/nextflow/nf-agent-pi:0.6.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates jq \
    && rm -rf /var/lib/apt/lists/*

COPY sdrf-skills /opt/sdrf-skills
WORKDIR /opt/sdrf-skills
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH=/opt/venv/bin:$PATH \
    CLAUDE_PLUGIN_ROOT=/opt/sdrf-skills \
    SDRF_SKILLS_ROOT=/opt/sdrf-skills
WORKDIR /opt/nf-agent-pi
ENTRYPOINT []
