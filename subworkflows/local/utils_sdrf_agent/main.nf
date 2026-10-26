include { validateParameters ; paramsSummaryLog ; samplesheetToList } from 'plugin/nf-schema'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW TO INITIALISE PIPELINE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow PIPELINE_INITIALISATION {
    take:
    input // string: path to the samplesheet

    main:
    validateParameters()
    log.info(paramsSummaryLog(workflow))

    // ref_sdrf is optional and only used in refine mode
    ch_samplesheet = channel.fromList(samplesheetToList(input, "${projectDir}/assets/schema_input.json"))
        .map { row ->
            def r = (row instanceof Map)
                ? [pxd: row.pxd, ref_sdrf: row.ref_sdrf]
                : [pxd: row[0], ref_sdrf: (row.size() >= 2 ? row[1] : null)]
            record(pxd: r.pxd as String, ref_sdrf: (r.ref_sdrf ? r.ref_sdrf as String : null))
        }

    emit:
    samplesheet = ch_samplesheet // records: pxd, ref_sdrf
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW FOR PIPELINE COMPLETION
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow PIPELINE_COMPLETION {
    take:
    summary // path: summary.tsv or refine_summary.tsv
    verdicts // records: pxd, verdict (the final verdict of each PXD)

    main:
    // A final FAIL is a content outcome, not an infrastructure error: warn, and stop only on request.
    // Wait for the summary, so that it is published before a stop.
    verdicts
        .toList()
        .map { rows -> record(rows: rows) }
        .combine(summary)
        .subscribe { all, _tsv ->
            def rows = all.rows
            def notPass = rows.findAll { r -> r.verdict != 'PASS' && r.verdict != 'LOW_CONF' }.collect { r -> r.pxd }.sort()
            def lowConf = rows.findAll { r -> r.verdict == 'LOW_CONF' }.collect { r -> r.pxd }.sort()
            if (notPass) {
                log.warn(
                    "Final review did not pass for ${notPass.size()} PXD(s): ${notPass.join(', ')}. " + "This is a content outcome, not an infrastructure error. See summary.tsv and review reports."
                )
            }
            if (lowConf) {
                log.warn(
                    "Final verdict is LOW_CONF for ${lowConf.size()} PXD(s): ${lowConf.join(', ')}. " + "Accepted and passed on; revisit if you want a stronger annotation."
                )
            }
            if (params.exit_on_review_fail && notPass) {
                error(
                    "exit_on_review_fail requested and ${notPass.size()} PXD(s) have a non-PASS final verdict: ${notPass.join(', ')}. " + "This is an intentional exit-on-content-fail; infra errors are handled separately by task retries."
                )
            }
        }
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

// Parsed JSON file, or null when the file is missing or unreadable
def readJson(json) {
    if (!json) {
        return null
    }
    try {
        return new groovy.json.JsonSlurper().parse(json.toFile())
    }
    catch (_e: Exception) {
        return null
    }
}

def verdictOf(review) {
    return readJson(review)?.verdict ?: 'FAIL'
}

def confidenceOf(review) {
    try {
        def c = readJson(review)?.confidence
        return c != null ? c as Float : -1.0
    }
    catch (_e: Exception) {
        return -1.0
    }
}

def parseReview(review) {
    return [verdict: verdictOf(review), conf: confidenceOf(review)]
}

// Run coverage for summary.tsv: the fraction, `unverifiable` after a coverage error, or `n/a`
def coverageOf(coverage) {
    def c = readJson(coverage)
    if (c == null) {
        return 'n/a'
    }
    return c.error ? 'unverifiable' : (c.fraction != null ? c.fraction as String : 'n/a')
}

def coverageFraction(coverage) {
    def f = readJson(coverage)?.fraction
    return f != null ? f as Float : null
}

// Accept the refined SDRF only if it is strictly better than the baseline:
//   - refined must PASS the independent adversarial review,
//   - refined coverage must be measurable and not worse than baseline,
//   - and either the baseline did not PASS (FAIL -> PASS) or the refined confidence is higher.
def isBetter(bv, fv, bc, fc) {
    if (fv.verdict != 'PASS') {
        return false
    }
    if (fc == null) {
        return false
    }
    if (bc != null && fc < bc) {
        return false
    }
    if (bv.verdict != 'PASS') {
        return true
    }
    return fv.conf > bv.conf
}

// software_versions.yml: the tool versions from the `versions` topic, plus the agent model and runner image
def softwareVersionsToYAML(rows) {
    def versions = rows
        .groupBy { r -> r[0].tokenize(':').last() }
        .collectEntries { process, entries -> [(process): entries.collectEntries { r -> [(r[1]): r[2]] }] }
    def agent = workflow.session.config.agent ?: [:]
    versions['Workflow'] = [
        (workflow.manifest.name): workflow.manifest.version,
        Nextflow: workflow.nextflow.version.toString(),
        agent_model: agent.model,
        agent_api_provider: agent.apiProvider,
        agent_container: agent.container,
    ]
    return new org.yaml.snakeyaml.Yaml().dumpAsMap(versions)
}
