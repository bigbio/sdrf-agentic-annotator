/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_ANNOTATE } from '../modules/local/sdrf_annotate'
include { SDRF_REVISE } from '../modules/local/sdrf_revise'
include { SDRF_REVISE as SDRF_REVISE_REV2 } from '../modules/local/sdrf_revise'
include { SCORE_SDRF } from '../subworkflows/local/score_sdrf'
include { SCORE_SDRF as SCORE_SDRF_REV1 } from '../subworkflows/local/score_sdrf'
include { SCORE_SDRF as SCORE_SDRF_REV2 } from '../subworkflows/local/score_sdrf'
include { verdictOf ; confidenceOf ; coverageOf } from '../subworkflows/local/utils_sdrf_agent'

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

    // The coverage precheck runs before each review
    SCORE_SDRF(ch_annotated)
    ch_reviewed = SCORE_SDRF.out.review
    ch_evidence = ch_annotated.map { r -> record(pxd: r.pxd, evidence: r.evidence) }

    // ---- bounded revise / escalation loop (improvement 3) ----
    // Statically unrolled with `if` guards (Nextflow DSL does not allow process calls in a for
    // loop). Each round re-runs coverage on the revised SDRF and re-reviews only the still-failing
    // records. A reproducible content FAIL is not a crash: it stays the final record for that PXD.
    ch_fail_round1 = ch_reviewed
        .filter { r -> verdictOf(r.review) != 'PASS' }
        .map { r -> tuple(r.pxd, r) }
        .join(ch_annotated.map { r -> tuple(r.pxd, r) })
        .map { pxd, review, ann -> record(pxd: pxd, sdrf: ann.sdrf, manifest: ann.manifest, review: review.review, samples: ann.samples, technical: ann.technical, evidence: ann.evidence) }

    ch_revised_all = channel.empty()
    ch_revised_review = channel.empty()
    if (params.revise && params.max_revise >= 1) {
        // ---- round 1 ----
        ch_rev1 = SDRF_REVISE(ch_fail_round1)
        ch_rev1_view = SCORE_SDRF_REV1(
            ch_rev1.join(ch_evidence, by: 'pxd')
        ).review

        ch_revised_all = ch_revised_all.mix(ch_rev1)
        ch_revised_review = ch_revised_review.mix(ch_rev1_view)

        // ---- round 2 (only if max_revise >= 2) ----
        ch_fail_round2 = ch_rev1_view
            .filter { r -> verdictOf(r.review) != 'PASS' }
            .map { r -> tuple(r.pxd, r) }
            .join(ch_rev1.map { r -> tuple(r.pxd, r) })
            .map { pxd, review, rev -> record(pxd: pxd, sdrf: rev.sdrf, manifest: rev.manifest, review: review.review, samples: rev.samples, technical: rev.technical) }
            .join(ch_evidence, by: 'pxd')

        if (params.max_revise >= 2) {
            ch_rev2 = SDRF_REVISE_REV2(ch_fail_round2)
            ch_rev2_view = SCORE_SDRF_REV2(
                ch_rev2.join(ch_evidence, by: 'pxd')
            ).review

            ch_revised_all = ch_revised_all.mix(ch_rev2)
            ch_revised_review = ch_revised_review.mix(ch_rev2_view)
        }
    }

    ch_summary = SDRF_SUMMARY(ch_reviewed, ch_revised_review).summary

    emit:
    annotated = ch_annotated
    reviewed = ch_reviewed
    revised = ch_revised_all
    revised_review = ch_revised_review
    coverage = SCORE_SDRF.out.coverage
    summary = ch_summary
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUMMARY - one summary.tsv row per PXD with the initial and final verdict
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow SDRF_SUMMARY {
    take:
    ch_reviewed // records: pxd, coverage, review of the first review
    ch_revised_review // records: pxd, coverage, review of each revise round

    main:
    // A revise round starts only after the previous review, so the last review of a PXD is its final one
    ch_last_review = ch_revised_review
        .map { r -> tuple(r.pxd, r) }
        .groupTuple()
        .map { pxd, reviews -> tuple(pxd, reviews.last()) }

    ch_final = ch_reviewed
        .map { r -> tuple(r.pxd, r) }
        .join(ch_last_review, remainder: true, failOnDuplicate: true)
        .map { pxd, ini, rev ->
            record(
                pxd: pxd,
                initial: verdictOf(ini.review),
                final: rev ? verdictOf(rev.review) : verdictOf(ini.review),
                revised: rev ? 'true' : 'false',
                review: (rev ? rev : ini).review,
                coverage: (rev ? rev : ini).coverage,
            )
        }
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

    ch_summary = ch_final.collectFile(
        name: 'summary.tsv',
        seed: 'pxd\tinitial_verdict\tfinal_verdict\trevised\tconfidence\tcoverage',
        newLine: true,
        sort: true,
    )

    // ---- exit behaviour (improvement 5): content FAIL != infrastructure error ----
    // The pipeline always publishes outputs and completes. A final content verdict of FAIL/LOW_CONF
    // is surfaced as a warning (not a crash) unless exit_on_review_fail is requested.
    ch_final
        .map { row -> row }
        .branch { row ->
            content_fail: row.split('\t')[2] != 'PASS'
            content_pass: true
        }
        .set { ch_by_verdict }
    ch_by_verdict.content_fail.subscribe { r ->
        log.warn(
            "Content verdict is not a clean PASS for ${r.split('\t')[0]} (final=${r.split('\t')[2]}). " + "This is a content outcome, not an infrastructure error. See summary.tsv."
        )
    }

    emit:
    summary = ch_summary
}
