/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REFINE_DECISION - accept the refined SDRF only if it scores strictly better than the baseline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
On the same review, the refined SDRF must be strictly better (see isBetter). Emits one
decision record per PXD with the chosen SDRF and its evidence manifest, review and coverage
report, plus <pxd>.refine_verdict.json files and refine_summary.tsv. A PXD without a refined
review keeps its baseline.
----------------------------------------------------------------------------------------
 */

include { REFINE_VERDICT } from '../../../modules/local/refine_verdict'
include { scoreOf ; isBetter ; gateVerdict } from '../utils_sdrf_agent'

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
    ch_verdict = REFINE_VERDICT(ch_decision.map { d -> record(pxd: d.pxd, json: d.json) })

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
    decision = ch_decision // records: pxd, chosen, final_verdict, scores, and the chosen sdrf, manifest, review, coverage
    verdict = ch_verdict // records: pxd, verdict (<pxd>.refine_verdict.json)
    summary = ch_summary // path: refine_summary.tsv
}
