nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_COVERAGE - deterministic run coverage of an SDRF against the PRIDE deposit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process that runs before each review. `sdrf-tools fetch` writes the
deposit's run list to evidence/files.json. `sdrf-tools audit-existing --json` compares it with
the SDRF's `comment[data file]` values. <pxd>.coverage.json is the `coverage` block of that
report: deposited_runs, annotated_runs, matched_runs, fraction, missing and invented.
If the deposit cannot be read, the file has `fraction: null` and an `error`.
<pxd>.checks.md holds the reviewer's deterministic checks (bin/sdrf_checks.py: SHA-256,
validate-sdrf for the active templates, sdrf-tools structure/check/score/reconcile,
convert-openms), so the review agent does not spend turns of its model on them.
----------------------------------------------------------------------------------------
 */

process SDRF_COVERAGE {

    tag "${pxd}"

    label 'process_single'

    // Exit 2 is a failed PRIDE lookup; after three retries the task writes an `error` instead.
    errorStrategy task.exitStatus == 2 ? 'retry' : 'terminate'
    maxRetries 3

    input:
    record(
        pxd: String,
        sdrf: Path
    )

    output:
    record(
        pxd: pxd,
        coverage: file("${pxd}.coverage.json"),
        checks: file("${pxd}.checks.md"),
    )

    topic:
    tuple(task.process, 'sdrf-skills-tools', eval('python -c "import importlib.metadata as m; print(m.version(\'sdrf-skills-tools\'))"')) >> 'versions'
    tuple(task.process, 'sdrf-pipelines', eval('python -c "import importlib.metadata as m; print(m.version(\'sdrf-pipelines\'))"')) >> 'versions'
    tuple(task.process, 'container', task.container) >> 'versions'

    script:
    // No early `exit 0`: the topic eval()s above are appended to the end of this script.
    """
    if sdrf-tools fetch ${pxd} --out evidence > fetch.log 2>&1; then
        # checks v2 (absolute paths). runs inside a zip of the deposit count as deposited runs (bin/archive_runs.py)
        archive_runs.py evidence/files.json > archive.log 2>&1 || true
        # Exit 1 only means the audit has blockers; the coverage block is still complete.
        sdrf-tools audit-existing ${sdrf} --runs evidence/files.json --json > audit.json || [ \$? -eq 1 ]
        jq '.coverage // {fraction: null, error: ([.findings[] | select(.code | IN("empty", "no_data_file_column")) | .summary] | join("; "))}' \\
            audit.json > ${pxd}.coverage.json
        sdrf_checks.py ${sdrf} ${pxd}.checks.md --record evidence/pride.json > checks.log 2>&1 || true
    else
        cat fetch.log >&2
        [ ${task.attempt} -gt 3 ] || exit 2
        jq -n --rawfile log fetch.log '{fraction: null, error: \$log}' > ${pxd}.coverage.json
        sdrf_checks.py ${sdrf} ${pxd}.checks.md > checks.log 2>&1 || true
    fi
    [ -s ${pxd}.checks.md ] || printf '# Deterministic checks\n\nThe checks could not run. Run them yourself.\n' > ${pxd}.checks.md
    """
}
