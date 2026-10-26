/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_COVERAGE - deterministic run coverage of an SDRF against the PRIDE deposit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process that runs before each review. `sdrf-tools fetch` writes the
deposit's run list to evidence/files.json. `sdrf-tools audit-existing --json` compares it with
the SDRF's `comment[data file]` values. <pxd>.coverage.json is the `coverage` block of that
report: deposited_runs, annotated_runs, matched_runs, fraction, missing and invented.
If the deposit cannot be read, the file has `fraction: null` and an `error`.
----------------------------------------------------------------------------------------
 */

process SDRF_COVERAGE {

    tag "${pxd}"

    container 'ghcr.io/bigbio/sdrf-agentic-annotator:dev'

    cpus 1
    memory '2 GB'

    // Exit 2 is a failed PRIDE lookup; after three retries the task writes an `error` instead.
    errorStrategy { task.exitStatus == 2 ? 'retry' : 'terminate' }
    maxRetries 3

    input:
    tuple val(pxd), path(sdrf), path(manifest)

    output:
    tuple val(pxd), path("${pxd}.coverage.json"), path(sdrf), path(manifest)

    script:
    """
    if ! sdrf-tools fetch ${pxd} --out evidence > fetch.log 2>&1; then
        cat fetch.log >&2
        [ ${task.attempt} -gt 3 ] || exit 2
        jq -n --rawfile log fetch.log '{fraction: null, error: \$log}' > ${pxd}.coverage.json
        exit 0
    fi

    # Exit 1 only means the audit has blockers; the coverage block is still complete.
    sdrf-tools audit-existing ${sdrf} --runs evidence/files.json --json > audit.json || [ \$? -eq 1 ]
    jq '.coverage // {fraction: null, error: ([.findings[] | select(.code | IN("empty", "no_data_file_column")) | .summary] | join("; "))}' \\
        audit.json > ${pxd}.coverage.json
    """
}
