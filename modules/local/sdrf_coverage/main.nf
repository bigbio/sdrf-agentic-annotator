/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_COVERAGE - deterministic coverage + file-existence precheck
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process that runs before the adversarial review. For one PRIDE
dataset, bin/sdrf_coverage.py:

1. Reads every `comment[data file]` value from the SDRF (basenames).
2. Fetches the PRIDE deposit file list for the PXD via the archive REST API.
3. Computes:
- matched     : SDRF data files whose basename exists in the deposit
- missing     : SDRF data files whose basename is NOT in the deposit
(a file-mapping hallucination, e.g. a reference to a .raw that
does not exist -> improvement 3)
- deposit_data: deposit RAW files (or peak lists when there are no RAW files);
search and result files are not counted
- coverage    : fraction of those deposit files that the SDRF represents
4. Writes a coverage.json that the reviewer MUST incorporate into its verdict.

This is cheap and deterministic, so the expensive adversarial pass only needs to
re-verify on top of it, and the coverage/subset gate (improvement 1) has a solid
numeric basis instead of an LLM guess.
----------------------------------------------------------------------------------------
 */

process SDRF_COVERAGE {

    tag "${pxd}"

    container 'ghcr.io/bigbio/sdrf-agentic-annotator:dev'

    cpus 1
    memory '2 GB'

    // Network is required to fetch the PRIDE file list. The script retries PRIDE itself and
    // writes a not_verifiable report if it stays unreachable; this retries anything else.
    errorStrategy 'retry'
    maxRetries 3

    input:
    tuple val(pxd), path(sdrf), path(manifest)

    output:
    tuple val(pxd), path("${pxd}.coverage.json"), path(sdrf), path(manifest)

    script:
    """
    sdrf_coverage.py --pxd ${pxd} --sdrf ${sdrf} --out ${pxd}.coverage.json
    """
}
