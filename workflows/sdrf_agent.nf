/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_ANNOTATE } from '../modules/local/sdrf_annotate'
include { SDRF_REVIEW } from '../modules/local/sdrf_review'
include { SDRF_REVISE } from '../modules/local/sdrf_revise'
include { SDRF_REVIEW as SDRF_REVIEW_REVISED } from '../modules/local/sdrf_review'

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

    // The reviewer gets the SDRF and the evidence manifest only, not the producer report
    ch_reviewed = SDRF_REVIEW(ch_annotated.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest) })

    ch_revised = channel.empty()
    ch_revised_review = channel.empty()
    if (params.revise) {
        ch_to_revise = ch_annotated
            .map { r -> tuple(r.pxd, r) }
            .join(ch_reviewed.filter { r -> verdictOf(r.review) != 'PASS' }.map { r -> tuple(r.pxd, r) })
            .map { pxd, annotated, reviewed -> record(pxd: pxd, sdrf: annotated.sdrf, manifest: annotated.manifest, review: reviewed.review) }

        ch_revised = SDRF_REVISE(ch_to_revise)
        ch_revised_review = SDRF_REVIEW_REVISED(ch_revised.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest) })
    }

    ch_summary = ch_reviewed
        .map { r -> tuple(r.pxd, verdictOf(r.review)) }
        .join(ch_revised_review.map { r -> tuple(r.pxd, verdictOf(r.review)) }, remainder: true)
        .map { pxd, initial, revised -> [pxd, initial, revised ?: initial, revised ? 'true' : 'false'].join('\t') }
        .collectFile(name: 'summary.tsv', seed: 'pxd\tinitial_verdict\tfinal_verdict\trevised', newLine: true, sort: true)

    emit:
    annotated = ch_annotated
    reviewed = ch_reviewed
    revised = ch_revised
    revised_review = ch_revised_review
    summary = ch_summary
}

def verdictOf(review) {
    return new groovy.json.JsonSlurper().parse(review.toFile()).verdict
}
