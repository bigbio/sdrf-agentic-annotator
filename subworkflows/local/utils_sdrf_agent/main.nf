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

    ch_pxds = channel.fromList(samplesheetToList(input, "${projectDir}/assets/schema_input.json"))
        .map { row -> row[0] }

    emit:
    pxds = ch_pxds
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW TO INITIALISE REFINE MODE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Samplesheet for `--refine` carries two columns: `pxd` (required) and `ref_sdrf` (optional
absolute path to an existing, already-published SDRF to refine). When `ref_sdrf` is empty the
pipeline fetches the existing SDRF from bigbio/sdrf-annotated-datasets instead.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow PIPELINE_REFINE_INITIALISATION {
    take:
    input // string: path to the samplesheet

    main:
    validateParameters()
    log.info(paramsSummaryLog(workflow))

    // samplesheetToList returns one list per row in schema column order (pxd, ref_sdrf), with
    // ref_sdrf as a Path. An empty or absent ref_sdrf comes back as an empty list.
    ch_rows = channel.fromList(samplesheetToList(input, "${projectDir}/assets/schema_input.json"))
        .map { row -> record(pxd: row[0] as String, ref_sdrf: row[1] ?: null) }

    emit:
    rows = ch_rows
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW TO SUMMARISE ANNOTATE MODE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
One row per PXD in summary.tsv. The final verdict comes from the latest review: revise
round 2, else round 1, else the initial review.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow SUMMARISE_REVIEWS {
    take:
    ch_reviewed // records: pxd, review, coverage (initial review)
    ch_rev1_view // records: pxd, review, coverage (review after revise round 1)
    ch_rev2_view // records: pxd, review, coverage (review after revise round 2)

    main:
    // One join per round, so each join sees at most one item per PXD and key
    ch_summary = ch_reviewed
        .map { r -> tuple(r.pxd, r) }
        .join(ch_rev1_view.map { r -> tuple(r.pxd, r) }, remainder: true)
        .join(ch_rev2_view.map { r -> tuple(r.pxd, r) }, remainder: true)
        .filter { _pxd, ini, _rev1, _rev2 -> ini }
        .map { pxd, ini, rev1, rev2 ->
            def last = rev2 ?: rev1 ?: ini
            def review = readReview(last.review)
            def verdict = gateVerdict(review.verdict, review.confidence, (params.confidence_gate as String).toDouble())
            def coverage = readCoverage(last.coverage)
            [pxd, readReview(ini.review).verdict, verdict, rev1 ? 'true' : 'false', review.confidence, coverageLabel(coverage)].join('\t')
        }
        .collectFile(
            name: 'summary.tsv',
            seed: 'pxd\tinitial_verdict\tfinal_verdict\trevised\tconfidence\tcoverage',
            newLine: true,
            sort: true,
        )

    emit:
    summary = ch_summary
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW FOR THE REFINE ACCEPTANCE GATE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Accept the refined SDRF only if, on the same review, it is strictly better than the
baseline (see isBetter). Emits one decision record per PXD with the chosen SDRF and its
evidence manifest, review and coverage report, plus <pxd>.refine_verdict.json files and
refine_summary.tsv.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow REFINE_DECISION {
    take:
    ch_base_rev // records: pxd, sdrf, manifest, coverage, review (baseline)
    ch_final_rev // records: pxd, sdrf, manifest, coverage, review (latest review of the refined SDRF)

    main:
    ch_decision = ch_base_rev
        .map { r -> tuple(r.pxd, r) }
        .join(ch_final_rev.map { r -> tuple(r.pxd, r) }, remainder: true)
        .filter { _pxd, b, _f -> b }
        .map { pxd, b, f ->
            def base = scoreOf(b)
            def refined = f ? scoreOf(f) : null
            def chosen = (refined && isBetter(base, refined)) ? 'refined' : 'baseline'
            def reason = !refined
                ? 'no refined review produced - kept existing SDRF'
                : (chosen == 'refined')
                    ? 'refined passes and is strictly better (verdict/confidence, coverage not worse)'
                    : 'refined not strictly better - kept existing SDRF'
            def pick = (chosen == 'refined') ? f : b
            def picked = (chosen == 'refined') ? refined : base
            record(
                pxd: pxd,
                chosen: chosen,
                final_verdict: gateVerdict(picked.verdict, picked.confidence, (params.confidence_gate as String).toDouble()),
                baseline: base,
                refined: refined,
                sdrf: pick.sdrf,
                manifest: pick.manifest,
                review: pick.review,
                coverage: pick.coverage,
                json: new groovy.json.JsonBuilder([
                    pxd: pxd,
                    chosen: chosen,
                    reason: reason,
                    baseline: [verdict: base.verdict, confidence: base.confidence, coverage: base.coverage],
                    refined: refined ? [verdict: refined.verdict, confidence: refined.confidence, coverage: refined.coverage] : null,
                ]).toPrettyString(),
            )
        }

    // One verdict file per PXD as soon as its decision is made
    ch_verdict = REFINE_VERDICT(ch_decision.map { d -> tuple(d.pxd, d.json) }).map { pxd, verdict -> record(pxd: pxd, verdict: verdict) }

    ch_summary = ch_decision
        .map { d ->
            [
                d.pxd,
                d.baseline.verdict,
                d.refined ? d.refined.verdict : 'n/a',
                d.chosen,
                d.baseline.coverage_label,
                d.refined ? d.refined.coverage_label : 'n/a',
                d.baseline.confidence,
                d.refined ? d.refined.confidence : 'n/a',
                d.final_verdict,
            ].join('\t')
        }
        .collectFile(
            name: 'refine_summary.tsv',
            seed: 'pxd\tbaseline_verdict\trefined_verdict\tchosen\tbaseline_coverage\trefined_coverage\tbaseline_confidence\trefined_confidence\tfinal_verdict',
            newLine: true,
            sort: true,
        )

    ch_decision.subscribe { d ->
        def refined = d.refined ? d.refined.verdict : 'n/a'
        if (d.chosen == 'baseline') {
            log.info("Refine: ${d.pxd} kept existing SDRF (baseline=${d.baseline.verdict}, refined=${refined})")
        }
        else {
            log.info("Refine: ${d.pxd} accepted refined SDRF (baseline=${d.baseline.verdict} -> refined=${refined})")
        }
    }

    emit:
    decision = ch_decision
    verdict = ch_verdict
    summary = ch_summary
}

// Writes <pxd>.refine_verdict.json in the task directory, without a container
process REFINE_VERDICT {
    tag "${pxd}"

    input:
    tuple val(pxd), val(json)

    output:
    tuple val(pxd), path("${pxd}.refine_verdict.json")

    exec:
    task.workDir.resolve("${pxd}.refine_verdict.json").text = json + '\n'
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW FOR PIPELINE COMPLETION
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow PIPELINE_COMPLETION {
    take:
    summary // path: summary.tsv or refine_summary.tsv, both with `pxd` and `final_verdict` columns

    main:
    summary.subscribe { tsv ->
        def rows = readSummary(tsv)
        def notPass = rows.findAll { r -> !(r.final_verdict in ['PASS', 'LOW_CONF']) }.collect { r -> r.pxd }
        def lowConf = rows.findAll { r -> r.final_verdict == 'LOW_CONF' }.collect { r -> r.pxd }
        if (notPass) {
            log.warn(
                "Final review did not pass for ${notPass.size()} PXD(s): ${notPass.join(', ')}. " + "This is a content outcome, not an infrastructure error. See ${tsv.name} and review reports."
            )
        }
        if (lowConf) {
            log.warn(
                "Final verdict is LOW_CONF for ${lowConf.size()} PXD(s): ${lowConf.join(', ')}. " + "Accepted and passed on; revisit if you want a stronger annotation."
            )
        }
        if (isTrue(params.exit_on_review_fail) && notPass) {
            error(
                "exit_on_review_fail requested and ${notPass.size()} PXD(s) have a non-PASS final verdict: ${notPass.join(', ')}. " + "This is an intentional exit-on-content-fail; infra errors are handled separately by task retries."
            )
        }
    }
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
HELPERS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

// Review input records (a channel helper): each SDRF with its evidence manifest, its coverage report
// and, where the producer wrote them, its validation output and evidence/ directory
def withCoverage(ch_sdrfs, ch_cov) {
    return ch_sdrfs
        .map { r -> tuple(r.pxd, r) }
        .join(ch_cov.map { pxd, cov, _sdrf, _manifest -> tuple(pxd, cov) })
        .map { pxd, r, cov -> record(pxd: pxd, sdrf: r.sdrf, manifest: r.manifest, coverage: cov, validation: r.validation, evidence: r.evidence) }
}

// Verdict and confidence of a review report written by an agent. A report the pipeline cannot
// read (e.g. JSON wrapped in a markdown code fence that is not JSON inside) is a FAIL with a
// warning, never a crash of the whole run. The verdict is upper-cased, so `pass` is a PASS.
def readReview(review) {
    def text = review.text.trim()
    if (text.startsWith('```')) {
        text = text.replaceFirst('^```[A-Za-z]*', '').replaceFirst('```$', '').trim()
    }
    def json = null
    try {
        json = new groovy.json.JsonSlurper().parseText(text)
    }
    catch (e: Exception) {
        log.warn("Cannot parse the review report ${review}: ${e.message}. Counting it as FAIL.")
    }
    if (!(json instanceof Map)) {
        return [verdict: 'FAIL', confidence: -1.0d]
    }
    def verdict = json.verdict ? (json.verdict as String).trim().toUpperCase() : 'FAIL'
    return [verdict: verdict, confidence: toConfidence(json.confidence)]
}

// Reviewer confidence as a number in 0..1, or -1 when it is missing or not a number in 0..1
def toConfidence(value) {
    try {
        def c = (value as String).toDouble()
        return (c >= 0 && c <= 1) ? c : -1.0d
    }
    catch (_e: Exception) {
        return -1.0d
    }
}

// A PASS below the confidence gate, or without a confidence, is accepted but flagged LOW_CONF
def gateVerdict(verdict, confidence, gate) {
    if (verdict == 'PASS' && gate > 0 && confidence < gate) {
        return 'LOW_CONF'
    }
    return verdict
}

// Fraction of the deposited runs that the SDRF annotates (or null) and the error, if any, of a
// SDRF_COVERAGE report (the `coverage` block of `sdrf-tools audit-existing --json`)
def readCoverage(coverage) {
    if (!coverage) {
        return [fraction: null, error: null]
    }
    try {
        def json = new groovy.json.JsonSlurper().parseText(coverage.text)
        def fraction = json.fraction != null ? (json.fraction as String).toDouble() : null
        return [fraction: fraction, error: json.error ?: null]
    }
    catch (_e: Exception) {
        return [fraction: null, error: null]
    }
}

// Coverage column of summary.tsv: `unverifiable` when the deposit could not be read, else the fraction or `n/a`
def coverageLabel(coverage) {
    if (coverage.error) {
        return 'unverifiable'
    }
    return coverage.fraction != null ? coverage.fraction as String : 'n/a'
}

// Verdict, confidence and coverage of one reviewed SDRF, as compared by the refine gate
def scoreOf(reviewed) {
    def review = readReview(reviewed.review)
    def coverage = readCoverage(reviewed.coverage)
    return [verdict: review.verdict, confidence: review.confidence, coverage: coverage.fraction, coverage_label: coverageLabel(coverage)]
}

// Accept the refined SDRF only if it is strictly better than the baseline:
//   - refined must PASS the independent adversarial review,
//   - refined coverage must be measurable and not worse than baseline,
//   - and either the baseline did not PASS (FAIL -> PASS) or the refined confidence is higher.
def isBetter(base, refined) {
    if (refined.verdict != 'PASS') {
        return false
    }
    if (refined.coverage == null) {
        return false
    }
    if (base.coverage != null && refined.coverage < base.coverage) {
        return false
    }
    if (base.verdict != 'PASS') {
        return true
    }
    return refined.confidence > base.confidence
}

// Rows of a summary TSV as maps keyed by its header
def readSummary(tsv) {
    def lines = tsv.readLines().findAll { line -> line.trim() }
    if (!lines) {
        return []
    }
    def header = lines[0].split('\t') as List
    return lines.drop(1).collect { line -> [header, line.split('\t', -1) as List].transpose().collectEntries() }
}

// Boolean parameter value. On the command line, `--revise false` arrives as the string 'false'.
def isTrue(value) {
    return (value instanceof Boolean) ? value : ((value as String)?.trim()?.toLowerCase() in ['true', 'yes', '1'])
}
