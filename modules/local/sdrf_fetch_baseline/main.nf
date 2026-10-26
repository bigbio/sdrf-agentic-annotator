/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_FETCH_BASELINE - fetch the existing, already-published SDRF for a PXD
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Used by refine mode when the samplesheet does not give a local `ref_sdrf` path. Locates and
downloads the SDRF that is already in bigbio/sdrf-annotated-datasets for the PXD and writes it
verbatim (unedited) as <pxd>.baseline.sdrf.tsv, to be used as the baseline to beat.
----------------------------------------------------------------------------------------
 */

agent SDRF_FETCH_BASELINE {
    maxIterations 60
    tools 'fs:*', 'shell:bash'

    instruction '''\
        You fetch the existing, already-published SDRF for one PRIDE dataset from the
        bigbio/sdrf-annotated-datasets repository. You run unattended inside a Nextflow task:
        never ask a question, never wait for a user, never use MCP tools.

        Environment facts (do not probe for them):
          - The canonical layout is:
              https://raw.githubusercontent.com/bigbio/sdrf-annotated-datasets/main/datasets/${pxd}/${pxd}.sdrf.tsv
          - If that URL 404s, search the repository (GitHub code search or the Git trees API) for
            the dataset's SDRF and download the one you find. Prefer the file whose basename is
            exactly ${pxd}.sdrf.tsv under a datasets/ path for ${pxd}.

        Download the existing SDRF and write it verbatim to ${pxd}.baseline.sdrf.tsv in the
        working directory. Do not edit or re-format it. If you cannot find the dataset in
        sdrf-annotated-datasets, stop and report a clear error - never fabricate a file.
        '''.stripIndent()

    input:
    pxd: String

    output:
    record(
        pxd: pxd,
        baseline: file("${pxd}.baseline.sdrf.tsv"),
    )

    prompt:
    """
    Fetch the existing SDRF for PRIDE dataset ${pxd} from bigbio/sdrf-annotated-datasets and
    write it verbatim to ${pxd}.baseline.sdrf.tsv in the working directory, then stop.
    """
}
