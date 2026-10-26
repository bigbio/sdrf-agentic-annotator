/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_SUMMARY - one summary.tsv row per PXD with the initial and final verdict
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { verdictOf ; confidenceOf ; coverageOf } from '../utils_sdrf_agent'

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
