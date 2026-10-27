/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUMMARISE_REVIEWS - one summary.tsv row per PXD with the initial and final verdict
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The final verdict comes from the latest review: revise round 2, else round 1, else the
initial review.
----------------------------------------------------------------------------------------
 */

include { readReview ; gateVerdict ; readCoverage ; coverageLabel } from '../utils_sdrf_agent'

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
    summary = ch_summary // path: summary.tsv
}
