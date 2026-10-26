/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_FREEZE_BASELINE - copies of the baseline SDRF in the work directory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process. <pxd>.baseline.sdrf.tsv is the baseline that refine mode reviews
and, if it is kept, publishes; a samplesheet `ref_sdrf` outside the work directory would not be
published. agent/<pxd>.baseline.sdrf.tsv is a separate copy for the refine agent, so nothing the
agent does to its input changes the baseline it is scored against or the user's file.
----------------------------------------------------------------------------------------
 */

process SDRF_FREEZE_BASELINE {

    tag "${pxd}"

    cpus 1
    memory '1 GB'

    input:
    tuple val(pxd), path(baseline, stageAs: 'input/*')

    output:
    tuple val(pxd), path("${pxd}.baseline.sdrf.tsv"), path("agent/${pxd}.baseline.sdrf.tsv")

    script:
    """
    cp -L ${baseline} ${pxd}.baseline.sdrf.tsv
    mkdir agent && cp ${pxd}.baseline.sdrf.tsv agent/
    """
}
