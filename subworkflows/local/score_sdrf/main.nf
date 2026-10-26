/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SCORE_SDRF - coverage precheck and independent adversarial review of an SDRF
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_COVERAGE } from '../../../modules/local/sdrf_coverage'
include { SDRF_REVIEW } from '../../../modules/local/sdrf_review'

workflow SCORE_SDRF {
    take:
    ch_sdrf // records: pxd, sdrf, manifest, validation (optional), evidence (optional)

    main:
    ch_coverage = SDRF_COVERAGE(ch_sdrf)

    // The reviewer gets the original request and the hand-off files, never the producer report
    ch_review = SDRF_REVIEW(
        ch_sdrf.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, validation: r.validation, evidence: r.evidence) }.join(ch_coverage, by: 'pxd')
    )

    emit:
    review = ch_review // records: pxd, sdrf, coverage, review
    coverage = ch_coverage // records: pxd, coverage
}
