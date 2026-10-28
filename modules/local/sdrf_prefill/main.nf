nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_PREFILL - what the PRIDE record already states, before the annotate agent starts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process. `sdrf-tools fetch` writes the PRIDE record and the deposit's file
list to evidence/. bin/sdrf_prefill.py turns them into <pxd>.prefill.json: organism,
instrument, organism part, disease, enzymes (the sdrf-tools digest dictionary), labels,
acquisition hints, the deposited run files and the search-parameter files. The agent starts from
these facts instead of looking them up again. If the lookup fails three times, the file has an
`error` and the agent gathers the record itself. Disable with --prefill false.
----------------------------------------------------------------------------------------
 */

process SDRF_PREFILL {

    tag "${pxd}"

    label 'process_single'

    // Exit 2 is a failed PRIDE or Europe PMC lookup; after three retries the task writes an `error` instead.
    errorStrategy task.exitStatus == 2 ? 'retry' : 'terminate'
    maxRetries 3

    input:
    pxd: String

    output:
    record(
        pxd: pxd,
        prefill: file("${pxd}.prefill.json"),
    )

    topic:
    tuple(task.process, 'sdrf-skills-tools', eval('python -c "import importlib.metadata as m; print(m.version(\'sdrf-skills-tools\'))"')) >> 'versions'
    tuple(task.process, 'container', task.container) >> 'versions'

    script:
    // No early `exit 0`: the topic eval()s above are appended to the end of this script.
    """
    if sdrf-tools fetch ${pxd} --out evidence > fetch.log 2>&1; then
        sdrf_prefill.py evidence ${pxd}.prefill.json
    else
        cat fetch.log >&2
        [ ${task.attempt} -gt 3 ] || exit 2
        jq -n --arg pxd ${pxd} --rawfile log fetch.log '{accession: \$pxd, error: \$log}' > ${pxd}.prefill.json
    fi
    """
}
