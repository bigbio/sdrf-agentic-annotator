/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUMMARISE_REVIEWS - one summary.tsv row per PXD with the initial and final verdict
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The final verdict comes from the latest review: revise round 2, else round 1, else the
initial review. If a revise round wrote its files but its review did not finish (the task failed
and was skipped), the final verdict is NO_REVIEW: the revised SDRF has no verdict, and the initial
FAIL does not stand in for it.
----------------------------------------------------------------------------------------
 */

include { readReview ; gateVerdict ; readCoverage ; coverageLabel } from '../utils_sdrf_agent'

workflow SUMMARISE_REVIEWS {
    take:
    ch_reviewed // records: pxd, review, coverage (initial review)
    ch_rev1_view // records: pxd, review, coverage (review after revise round 1)
    ch_rev2_view // records: pxd, review, coverage (review after revise round 2)
    ch_revised // records: pxd, dir of every revise round that wrote its files ('revised' or 'revised_2')

    main:
    ch_ran1 = ch_revised.filter { r -> r.dir == 'revised' }.map { r -> tuple(r.pxd, true) }
    ch_ran2 = ch_revised.filter { r -> r.dir == 'revised_2' }.map { r -> tuple(r.pxd, true) }
    // One join per round, so each join sees at most one item per PXD and key
    ch_summary = ch_reviewed
        .map { r -> tuple(r.pxd, r) }
        .join(ch_rev1_view.map { r -> tuple(r.pxd, r) }, remainder: true)
        .join(ch_rev2_view.map { r -> tuple(r.pxd, r) }, remainder: true)
        .join(ch_ran1, remainder: true)
        .join(ch_ran2, remainder: true)
        .filter { _pxd, ini, _rev1, _rev2, _ran1, _ran2 -> ini }
        .map { pxd, ini, rev1, rev2, ran1, ran2 ->
            def round2 = ran2 || rev2
            def round1 = ran1 || rev1
            def last = round2 ? rev2 : (round1 ? rev1 : ini)
            def initial = readReview(ini.review).verdict
            if (!last) {
                return [pxd, initial, 'NO_REVIEW', 'true', 'NA', 'NA'].join('\t')
            }
            def review = readReview(last.review)
            def verdict = gateVerdict(review.verdict, review.confidence, (params.confidence_gate as String).toDouble())
            def coverage = readCoverage(last.coverage)
            [pxd, initial, verdict, round1 ? 'true' : 'false', review.confidence, coverageLabel(coverage)].join('\t')
        }
        .collectFile(
            name: 'summary.tsv',
            seed: 'pxd\tinitial_verdict\tfinal_verdict\trevised\tconfidence\tcoverage',
            newLine: true,
            sort: true,
        )
        .ifEmpty { error('No PXD finished its first review: every annotate or review task failed or was skipped. See .nextflow.log.') }

    emit:
    summary = ch_summary // path: summary.tsv
}
