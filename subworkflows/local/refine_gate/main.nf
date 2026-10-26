/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REFINE_GATE - accept the refined SDRF only if it scores strictly better than the baseline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Writes one <pxd>.refine_verdict.json per PXD and refine_summary.tsv. A PXD without a
refined review keeps its baseline.
----------------------------------------------------------------------------------------
 */

include { REFINE_VERDICT } from '../../../modules/local/refine_verdict'
include { parseReview ; coverageFraction ; isBetter } from '../utils_sdrf_agent'

workflow REFINE_GATE {
    take:
    ch_baseline_review // records: pxd, sdrf, coverage, review of the baseline SDRF
    ch_refined_review // records: pxd, sdrf, coverage, review of the refined SDRF, if any

    main:
    ch_decision = ch_baseline_review
        .map { r -> tuple(r.pxd, r) }
        .join(ch_refined_review.map { r -> tuple(r.pxd, r) }, remainder: true, failOnDuplicate: true)
        .map { pxd, b, f ->
            def bv = parseReview(b.review)
            def bc = coverageFraction(b.coverage)
            def fv = f ? parseReview(f.review) : [verdict: 'n/a', conf: null]
            def fc = f ? coverageFraction(f.coverage) : null
            def chosen = f && isBetter(bv, fv, bc, fc) ? 'refined' : 'baseline'
            def reason = !f
                ? 'no refined verdict produced - kept existing SDRF'
                : chosen == 'refined'
                    ? 'refined passes and is strictly better (verdict/confidence, coverage not worse)'
                    : 'refined not strictly better - kept existing SDRF'
            record(
                pxd: pxd,
                baseline_verdict: bv.verdict,
                baseline_confidence: bv.conf,
                baseline_coverage: bc,
                refined_verdict: fv.verdict,
                refined_confidence: fv.conf,
                refined_coverage: fc,
                chosen: chosen,
                chosen_sdrf: chosen == 'refined' ? f.sdrf : b.sdrf,
                json: new groovy.json.JsonBuilder([
                    pxd: pxd,
                    chosen: chosen,
                    reason: reason,
                    baseline: [verdict: bv.verdict, confidence: bv.conf, coverage: bc],
                    refined: f ? [verdict: fv.verdict, confidence: fv.conf, coverage: fc] : null,
                ]).toString(),
            )
        }

    ch_verdict = REFINE_VERDICT(ch_decision.map { d -> record(pxd: d.pxd, json: d.json) })

    ch_summary = ch_decision
        .map { d -> [d.pxd, d.baseline_verdict, d.refined_verdict, d.chosen, d.baseline_coverage, d.refined_coverage, d.baseline_confidence, d.refined_confidence].join('\t') }
        .collectFile(
            name: 'refine_summary.tsv',
            seed: 'pxd\tbaseline_verdict\trefined_verdict\tchosen\tbaseline_coverage\trefined_coverage\tbaseline_confidence\trefined_confidence',
            newLine: true,
            sort: true,
        )

    ch_decision.subscribe { d ->
        if (d.chosen == 'baseline') {
            log.info("Refine: ${d.pxd} kept existing SDRF (baseline=${d.baseline_verdict}, refined=${d.refined_verdict})")
        }
        else {
            log.info("Refine: ${d.pxd} accepted refined SDRF (baseline=${d.baseline_verdict} -> refined=${d.refined_verdict})")
        }
    }

    emit:
    decision = ch_decision // records: pxd, verdicts, confidences, coverages, chosen, chosen_sdrf, json
    verdict = ch_verdict // records: pxd, verdict (<pxd>.refine_verdict.json)
    summary = ch_summary // path: refine_summary.tsv
}
