nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_PREFILL - what the PRIDE record already states, before the annotate agent starts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process. `sdrf-tools fetch` writes the PRIDE record and the deposit's file
list to evidence/. bin/sdrf_prefill.py turns them into <pxd>.prefill.json: organism,
instrument, organism part, disease, enzymes (the sdrf-tools digest dictionary), labels,
acquisition hints, the deposited run files and the search-parameter files. The agent starts from
these facts instead of looking them up again. Disable with --prefill false.
----------------------------------------------------------------------------------------
 */

process SDRF_PREFILL {

    tag "${pxd}"

    label 'process_single'

    // Exit 2 is a failed PRIDE lookup (network); any other failure is final.
    errorStrategy task.exitStatus == 2 && task.attempt <= 3 ? 'retry' : 'terminate'

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
    """
    sdrf-tools fetch ${pxd} --out evidence > fetch.log 2>&1 || { cat fetch.log >&2; exit 2; }
    sdrf_prefill.py evidence ${pxd}.prefill.json
    """
}
