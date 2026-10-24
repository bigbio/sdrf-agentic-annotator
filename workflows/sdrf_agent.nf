/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_ANNOTATE } from '../modules/local/sdrf_annotate'
include { SDRF_REVIEW } from '../modules/local/sdrf_review'
include { SDRF_REVISE } from '../modules/local/sdrf_revise'
include { SDRF_REVIEW as SDRF_REVIEW_REVISED } from '../modules/local/sdrf_review'
include { SDRF_COVERAGE } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_REV1 } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_REV2 } from '../modules/local/sdrf_coverage'
include { SDRF_REVISE as SDRF_REVISE_REV2 } from '../modules/local/sdrf_revise'
include { SDRF_REVIEW as SDRF_REVIEW_REVISED_REV2 } from '../modules/local/sdrf_review'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow SDRF_AGENT {
    take:
    ch_pxds // channel: PXD accessions

    main:
    ch_annotated = SDRF_ANNOTATE(ch_pxds)

    // ---- deterministic coverage precheck (improvement 1 + file-existence, improvement 3) ----
    // Runs the SDRF's data files against the PRIDE deposit file list BEFORE the adversarial pass.
    ch_initial_cov = SDRF_COVERAGE(ch_annotated.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })
    // The reviewer gets the SDRF, the evidence manifest, and the coverage report (not the producer report)
    ch_initial_review_in = ch_annotated
        .map { r -> tuple(r.pxd, r) }
        .join(ch_initial_cov.map { pxd, cov, sdrf, manifest -> tuple(pxd, cov) }, remainder: true)
        .map { pxd, ann, cov -> record(pxd: pxd, sdrf: ann.sdrf, manifest: ann.manifest, coverage: cov) }
    ch_reviewed = SDRF_REVIEW(ch_initial_review_in)

    // ---- bounded revise / escalation loop (improvement 3) ----
    // Statically unrolled with `if` guards (Nextflow DSL does not allow process calls in a for
    // loop). Each round re-runs coverage on the revised SDRF and re-reviews only the still-failing
    // records. A reproducible content FAIL is not a crash: it stays the final record for that PXD.
    ch_fail_round1 = ch_reviewed
        .filter { r -> verdictOf(r.review) != 'PASS' }
        .map { r -> tuple(r.pxd, r) }
        .join(ch_annotated.map { r -> tuple(r.pxd, r) })
        .map { pxd, review, ann -> record(pxd: pxd, sdrf: ann.sdrf, manifest: ann.manifest, review: review.review) }

    ch_revised_all = channel.empty()
    ch_revised_review = channel.empty()
    if (params.revise && params.max_revise >= 1) {
        // ---- round 1 ----
        ch_rev1 = SDRF_REVISE(ch_fail_round1)
        ch_rev1_cov = SDRF_COVERAGE_REV1(ch_rev1.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })
        ch_rev1_in = ch_rev1
            .map { r -> tuple(r.pxd, r) }
            .join(ch_rev1_cov.map { pxd, cov, sdrf, manifest -> tuple(pxd, cov) }, remainder: true)
            .map { pxd, rev, cov -> record(pxd: pxd, sdrf: rev.sdrf, manifest: rev.manifest, coverage: cov) }
        ch_rev1_view = SDRF_REVIEW_REVISED(ch_rev1_in)

        ch_revised_all = ch_revised_all.mix(ch_rev1)
        ch_revised_review = ch_revised_review.mix(ch_rev1_view)

        // ---- round 2 (only if max_revise >= 2) ----
        ch_fail_round2 = ch_rev1_view
            .filter { r -> verdictOf(r.review) != 'PASS' }
            .map { r -> tuple(r.pxd, r) }
            .join(ch_rev1.map { r -> tuple(r.pxd, r) })
            .map { pxd, review, rev -> record(pxd: pxd, sdrf: rev.sdrf, manifest: rev.manifest, review: review.review) }

        if (params.max_revise >= 2) {
            ch_rev2 = SDRF_REVISE_REV2(ch_fail_round2)
            ch_rev2_cov = SDRF_COVERAGE_REV2(ch_rev2.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })
            ch_rev2_in = ch_rev2
                .map { r -> tuple(r.pxd, r) }
                .join(ch_rev2_cov.map { pxd, cov, sdrf, manifest -> tuple(pxd, cov) }, remainder: true)
                .map { pxd, rev, cov -> record(pxd: pxd, sdrf: rev.sdrf, manifest: rev.manifest, coverage: cov) }
            ch_rev2_view = SDRF_REVIEW_REVISED_REV2(ch_rev2_in)

            ch_revised_all = ch_revised_all.mix(ch_rev2)
            ch_revised_review = ch_revised_review.mix(ch_rev2_view)
        }
    }

    // ---- summary with coverage + confidence + content-vs-infra classification ----
    ch_final = ch_reviewed
        .map { r -> tuple(r.pxd, r) }
        .join(ch_revised_review.map { r -> tuple(r.pxd, r) }, remainder: true)
        .map { pxd, ini, rev -> record(
                pxd: pxd,
                initial: verdictOf(ini.review),
                final: rev ? verdictOf(rev.review) : verdictOf(ini.review),
                revised: rev ? 'true' : 'false',
                review: (rev ? rev : ini).review,
                coverage: (rev ? rev : ini).coverage
            ) }
        .map { r ->
            def verdict = r.final
            def confidence = confidenceOf(r.review)
            def gate = (params.confidence_gate as String).toDouble()
            // confidence gate (improvement 2): low-confidence PASS is still accepted and passed on,
            // but flagged LOW_CONF so the operator can decide to revisit.
            if (verdict == 'PASS' && gate > 0 && confidence >= 0 && confidence < gate) {
                verdict = 'LOW_CONF'
            }
            def cov = coverageOf(r.coverage)
            [r.pxd, r.initial, verdict, r.revised, confidence, cov].join('\t')
        }

    ch_summary = ch_final
        .collectFile(name: 'summary.tsv',
                     seed: 'pxd\tinitial_verdict\tfinal_verdict\trevised\tconfidence\tcoverage',
                     newLine: true, sort: true)

    // ---- exit behaviour (improvement 5): content FAIL != infrastructure error ----
    // The pipeline always publishes outputs and completes. A final content verdict of FAIL/LOW_CONF
    // is surfaced as a warning (not a crash) unless exit_on_review_fail is requested.
    ch_final.map { it }
        .branch {
            content_fail: it.split('\t')[2] != 'PASS'
            content_pass:  true
        }
        .set { ch_by_verdict }
    ch_by_verdict.content_fail.subscribe { r ->
        log.warn("Content verdict is not a clean PASS for ${r.split('\t')[0]} (final=${r.split('\t')[2]}). " +
                 "This is a content outcome, not an infrastructure error. See summary.tsv.")
    }

    emit:
    annotated = ch_annotated
    reviewed = ch_reviewed
    revised = ch_revised_all
    revised_review = ch_revised_review
    coverage = ch_initial_cov.map { pxd, cov, sdrf, manifest -> record(pxd: pxd, coverage: cov) }
    summary = ch_summary
}

def verdictOf(review) {
    return new groovy.json.JsonSlurper().parse(review.toFile()).verdict ?: 'FAIL'
}

def confidenceOf(review) {
    try {
        def c = new groovy.json.JsonSlurper().parse(review.toFile()).confidence
        return c != null ? c as double : -1.0
    } catch (Exception e) {
        return -1.0
    }
}

def coverageOf(coverage) {
    if (!coverage) return 'n/a'
    try {
        def c = new groovy.json.JsonSlurper().parse(coverage.toFile())
        return c.status == 'ok' ? (c.coverage != null ? c.coverage as String : 'n/a') : 'unverifiable'
    } catch (Exception e) {
        return 'n/a'
    }
}
