nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_FETCH_BASELINE - download the existing SDRF for a PXD
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process. Refine mode uses it when the samplesheet gives no `ref_sdrf`.
`sdrf-tools curated` lists the SDRFs of the PXD in bigbio/sdrf-annotated-datasets. The
process downloads <PXD>.sdrf.tsv (or the only listed file) verbatim as <pxd>.baseline.sdrf.tsv.
It fails when the PXD has no curated SDRF, or has several and none is <PXD>.sdrf.tsv.
----------------------------------------------------------------------------------------
 */

process SDRF_FETCH_BASELINE {

    tag "${pxd}"

    container 'ghcr.io/bigbio/sdrf-agentic-annotator:dev'

    cpus 1
    memory 2.GB

    // Exit 2 is a failed lookup or download (network); any other failure is final.
    errorStrategy task.exitStatus == 2 && task.attempt <= 3 ? 'retry' : 'terminate'

    input:
    pxd: String

    output:
    record(
        pxd: pxd,
        baseline: file("${pxd}.baseline.sdrf.tsv"),
    )

    script:
    """
    set -uo pipefail
    acc=\$(echo '${pxd}' | tr '[:lower:]' '[:upper:]')

    sdrf-tools curated "\$acc" > curated.json || exit 2
    jq -r --arg acc "\$acc" '.[\$acc][].file' curated.json > files.txt
    n=\$(wc -l < files.txt)

    if [ "\$n" -eq 0 ]; then
        echo "ERROR: bigbio/sdrf-annotated-datasets has no SDRF for \$acc. Refine mode needs one: set ref_sdrf in the samplesheet or annotate without --refine." >&2
        exit 1
    fi
    sdrf=\$(grep -x "datasets/\$acc/\$acc.sdrf.tsv" files.txt || true)
    if [ -z "\$sdrf" ] && [ "\$n" -eq 1 ]; then
        sdrf=\$(cat files.txt)
    fi
    if [ -z "\$sdrf" ]; then
        echo "ERROR: bigbio/sdrf-annotated-datasets has \$n SDRFs for \$acc and none is \$acc.sdrf.tsv. Set ref_sdrf in the samplesheet to choose one:" >&2
        sed 's/^/  /' files.txt >&2
        exit 1
    fi

    curl -fsSL "https://raw.githubusercontent.com/bigbio/sdrf-annotated-datasets/HEAD/\$sdrf" -o ${pxd}.baseline.sdrf.tsv || exit 2
    head -1 ${pxd}.baseline.sdrf.tsv | cut -f1 | tr -d '\\r\\357\\273\\277' | grep -qix 'source name' || {
        echo "ERROR: \$sdrf did not download as an SDRF table." >&2
        exit 2
    }
    """
}
