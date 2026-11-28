nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_STAMP - name this pipeline and the samples of a passing SDRF
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process. The agents write `manual curation`, which is wrong for an SDRF
that a model produced. bin/sdrf_stamp.py sets `NT=sdrf-agentic-annotator;VV=v<version>`, renames the samples to
`<PXD>-Sample-<n>` (the original names go to <PXD>.sample_names.tsv), and
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
        names: file("${pxd}.sample_names.tsv"),
    )

    topic:
    tuple(task.process, 'sdrf-pipelines', eval('python -c "import importlib.metadata as m; print(m.version(\'sdrf-pipelines\'))"')) >> 'versions'
    tuple(task.process, 'container', task.container) >> 'versions'

    script:
    """
    # The input is staged as a link that can have the output's name: writing <pxd>.sdrf.tsv directly would
    # rewrite the source SDRF through it. Write to a new file, remove the link (not its target), then rename.
    sdrf_stamp.py ${sdrf} stamped.sdrf.tsv.tmp ${workflow.manifest.version} ${pxd} ${pxd}.sample_names.tsv
    rm -f ${pxd}.sdrf.tsv
    mv stamped.sdrf.tsv.tmp ${pxd}.sdrf.tsv
    parse_sdrf validate-sdrf --sdrf_file ${pxd}.sdrf.tsv --use_ols_cache_only > ${pxd}.stamp_validation.txt 2>&1 || { cat ${pxd}.stamp_validation.txt >&2; exit 1; }
    """
}
