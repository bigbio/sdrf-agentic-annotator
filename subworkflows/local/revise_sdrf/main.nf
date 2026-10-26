/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REVISE_SDRF - one revise round: revise a failed SDRF, then score the revised SDRF again
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_REVISE } from '../../../modules/local/sdrf_revise'
include { SCORE_SDRF } from '../score_sdrf'

workflow REVISE_SDRF {
    take:
    ch_failed // records: pxd, sdrf, manifest, review, samples, technical, evidence (all but the first four optional)

    main:
    ch_revised = SDRF_REVISE(ch_failed)
    SCORE_SDRF(ch_revised.join(ch_failed.map { r -> record(pxd: r.pxd, evidence: r.evidence) }, by: 'pxd'))

    emit:
    revised = ch_revised // records: SDRF_REVISE output
    review = SCORE_SDRF.out.review // records: pxd, sdrf, coverage, review
}
