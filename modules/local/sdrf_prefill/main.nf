nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_PREFILL - what the PRIDE record already states, before the annotate agent starts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process. `sdrf-tools fetch` writes the PRIDE record and the deposit's file
list to evidence/. bin/sdrf_prefill.py turns them into <pxd>.prefill.json: organism,
instrument, organism part, disease, enzymes (the sdrf-tools digest dictionary), labels,
acquisition hints, the fragmentation method read from the embedded method of the deposited Thermo RAW files
(bin/raw_dissociation.py), the deposited run files and the search-parameter files. The agent starts from
these facts instead of looking them up again. If the lookup fails three times, the file has an
`error` and the agent gathers the record itself. Disable with --prefill false.
bin/sdrf_sheet.py then writes <pxd>.sheet.md, the evidence sheet the annotate agent starts from: the methods of
the manuscript, ontology term matches (ontology_dir, corpus_index), search settings found by pattern, the design
read from the run file names and similar SDRFs of the corpus. It calls no model and never fails the task.
----------------------------------------------------------------------------------------
 */

process SDRF_PREFILL {

    tag "${pxd}"

    label 'process_single'

    // Exit 2 is a failed PRIDE or Europe PMC lookup. Europe PMC answers 500 in bursts, so each retry waits
    // 1, 2 then 3 minutes; after three retries the task writes an `error` instead. The wait is in the
    // directive, not the script, so the task hash (and -resume of running campaigns) is unchanged.
    errorStrategy {
        if (task.exitStatus == 2) {
            sleep(60000L * task.attempt)
            return 'retry'
        }
        return 'terminate'
    }
    maxRetries 3

    input:
    record(
        pxd: String,
        ontology_dir: Path?,
        corpus_index: Path?
    )

    output:
    record(
        pxd: pxd,
        prefill: file("${pxd}.prefill.json"),
        sheet: file("${pxd}.sheet.md"),
        prefetched: file("prefetched"),
    )

    topic:
    tuple(task.process, 'sdrf-skills-tools', eval('python -c "import importlib.metadata as m; print(m.version(\'sdrf-skills-tools\'))"')) >> 'versions'
    tuple(task.process, 'container', task.container) >> 'versions'

    script:
    // No early `exit 0`: the topic eval()s above are appended to the end of this script.
    """
    mkdir -p prefetched
    if sdrf-tools fetch ${pxd} --out evidence > fetch.log 2>&1; then
        archive_runs.py evidence/files.json > archive.log 2>&1 || true
        raw_dissociation.py ${pxd} ${pxd}.dissociation.json > raw.log 2>&1 || echo '{}' > ${pxd}.dissociation.json
        sdrf_prefill.py evidence ${pxd}.prefill.json ${pxd}.dissociation.json
        # What the annotate agent would otherwise fetch again: the record, the curated-SDRF lookup and the manifest schema
        cp -r evidence/. prefetched/
        sdrf-tools curated ${pxd} > prefetched/curated.txt 2>&1 || true
        sdrf-tools schema-check --print-schema evidence-manifest > prefetched/evidence-manifest.schema.json 2>/dev/null || rm -f prefetched/evidence-manifest.schema.json
        sdrf_sheet.py evidence ${pxd}.prefill.json ${pxd} ${ontology_dir ? "--ontology-dir ${ontology_dir}" : ''} ${corpus_index ? "--corpus-index ${corpus_index}" : ''} > sheet.log 2>&1 \\
            || printf '# Evidence sheet for %s\\n\\n## Not available\\n- the sheet could not be built: gather the evidence yourself\\n' ${pxd} > ${pxd}.sheet.md
    else
        cat fetch.log >&2
        [ ${task.attempt} -gt 3 ] || exit 2
        jq -n --arg pxd ${pxd} --rawfile log fetch.log '{accession: \$pxd, error: \$log}' > ${pxd}.prefill.json
        printf '# Evidence sheet for %s\\n\\n## Not available\\n- the PRIDE record could not be fetched\\n' ${pxd} > ${pxd}.sheet.md
    fi
    """
}
