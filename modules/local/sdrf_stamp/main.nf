nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_STAMP - name this pipeline in the annotation tool column of a passing SDRF
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process. The agents write `manual curation`, which is wrong for an SDRF
that a model produced. bin/sdrf_stamp.py sets `NT=sdrf-agentic-annotator;VV=v<version>`, and
`parse_sdrf validate-sdrf` (the command that CI of bigbio/sdrf-annotated-datasets runs) has to pass
on the stamped file, so what is published is what was validated. Nothing else in the file changes.
----------------------------------------------------------------------------------------
 */

process SDRF_STAMP {

    tag "${pxd}"

    label 'process_single'

    // A stamped SDRF that does not validate is skipped and logged, so one dataset does not stop the others.
    errorStrategy 'ignore'

    input:
    record(
        pxd: String,
        sdrf: Path
    )

    output:
    record(
        pxd: pxd,
        sdrf: file("${pxd}.sdrf.tsv"),
        validation: file("${pxd}.stamp_validation.txt"),
    )

    topic:
    tuple(task.process, 'sdrf-pipelines', eval('python -c "import importlib.metadata as m; print(m.version(\'sdrf-pipelines\'))"')) >> 'versions'
    tuple(task.process, 'container', task.container) >> 'versions'

    script:
    """
    sdrf_stamp.py ${sdrf} ${pxd}.sdrf.tsv ${workflow.manifest.version}
    parse_sdrf validate-sdrf --sdrf_file ${pxd}.sdrf.tsv --use_ols_cache_only > ${pxd}.stamp_validation.txt 2>&1 || { cat ${pxd}.stamp_validation.txt >&2; exit 1; }
    """
}
