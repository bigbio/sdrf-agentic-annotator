#!/usr/bin/env nextflow
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
bigbio/sdrf-agentic-annotator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Github : https://github.com/bigbio/sdrf-agentic-annotator
----------------------------------------------------------------------------------------
 */

include { SDRF_AGENT } from './workflows/sdrf_agent'
include { SDRF_REFINE_AGENT } from './workflows/sdrf_refine_agent'
include { PIPELINE_INITIALISATION ; PIPELINE_REFINE_INITIALISATION ; PIPELINE_COMPLETION } from './subworkflows/local/utils_sdrf_agent'

workflow {

    main:
    // Unified publish channel placeholders: each is populated by the branch that produces it and
    // stays empty in the other mode, so the publish/output blocks below stay flat (no if/else).
    ch_summary = Channel.empty()
    ch_annotated = Channel.empty()
    ch_reviewed = Channel.empty()
    ch_revised = Channel.empty()
    ch_revised_review = Channel.empty()
    ch_coverage = Channel.empty()
    ch_refine_decision = Channel.empty()
    ch_refine_verdict = Channel.empty()

    if (params.refine) {
        PIPELINE_REFINE_INITIALISATION(params.input)
        SDRF_REFINE_AGENT(PIPELINE_REFINE_INITIALISATION.out.rows)
        PIPELINE_COMPLETION(SDRF_REFINE_AGENT.out.summary)
        ch_summary = SDRF_REFINE_AGENT.out.summary
        ch_refine_decision = SDRF_REFINE_AGENT.out.decision
        ch_refine_verdict = SDRF_REFINE_AGENT.out.verdict
    }
    else {
        PIPELINE_INITIALISATION(params.input)
        SDRF_AGENT(PIPELINE_INITIALISATION.out.pxds)
        PIPELINE_COMPLETION(SDRF_AGENT.out.summary)
        ch_summary = SDRF_AGENT.out.summary
        ch_annotated = SDRF_AGENT.out.annotated
        ch_reviewed = SDRF_AGENT.out.reviewed
        ch_revised = SDRF_AGENT.out.revised
        ch_revised_review = SDRF_AGENT.out.revised_review
        ch_coverage = SDRF_AGENT.out.coverage
    }

    publish:
    summary = ch_summary
    annotated = ch_annotated
    reviewed = ch_reviewed
    revised = ch_revised
    revised_review = ch_revised_review
    coverage = ch_coverage
    refine_decision = ch_refine_decision
    refine_verdict = ch_refine_verdict
}
output {
    annotated {
        path { r -> r.pxd }
    }
    reviewed {
        path { r -> r.pxd }
    }
    revised {
        path { r -> "${r.pxd}/revised" }
    }
    revised_review {
        path { r -> "${r.pxd}/revised" }
    }
    coverage {
        path { r -> r.pxd }
    }
    summary {
        path '.'
    }
    refine_decision {
        path { r -> r.pxd }
    }
    refine_verdict {
        path { r -> r.pxd }
    }
}
