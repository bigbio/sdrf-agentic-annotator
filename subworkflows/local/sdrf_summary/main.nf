/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_SUMMARY - one summary.tsv row per PXD with the initial and final verdict
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { verdictOf ; confidenceOf ; coverageOf } from '../utils_sdrf_agent'

workflow SDRF_SUMMARY {
    take:
    ch_reviewed // records: pxd, coverage, review of the first review
    ch_revised_review // records: pxd, coverage, review of each revise round, in round order per PXD

    main:
    // A revise round starts only after the previous review, so the last review of a PXD is its final one
    ch_last_review = ch_revised_review
        .map { r -> tuple(r.pxd, r) }
        .groupTuple()
        .map { pxd, reviews -> tuple(pxd, reviews.last()) }

    ch_rows = ch_reviewed
        .map { r -> tuple(r.pxd, r) }
        .join(ch_last_review, remainder: true, failOnDuplicate: true)
        .map { pxd, initial, last ->
            def review = last ?: initial
            def verdict = verdictOf(review.review)
            def confidence = confidenceOf(review.review)
            def gate = (params.confidence_gate as String).toDouble()
            // A low-confidence PASS is still accepted, but flagged LOW_CONF so that it can be checked again
            if (verdict == 'PASS' && gate > 0 && confidence >= 0 && confidence < gate) {
                verdict = 'LOW_CONF'
            }
            record(
                pxd: pxd,
                initial_verdict: verdictOf(initial.review),
                final_verdict: verdict,
                revised: last ? 'true' : 'false',
                confidence: confidence,
                coverage: coverageOf(review.coverage),
            )
        }

    ch_summary = ch_rows
        .map { r -> [r.pxd, r.initial_verdict, r.final_verdict, r.revised, r.confidence, r.coverage].join('\t') }
        .collectFile(
            name: 'summary.tsv',
            seed: 'pxd\tinitial_verdict\tfinal_verdict\trevised\tconfidence\tcoverage',
            newLine: true,
            sort: true,
        )

    emit:
    summary = ch_summary // path: summary.tsv
    verdicts = ch_rows.map { r -> record(pxd: r.pxd, verdict: r.final_verdict) } // records: pxd, verdict
}
