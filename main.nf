#!/usr/bin/env nextflow
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
bigbio/sdrf-agentic-annotator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Github : https://github.com/bigbio/sdrf-agentic-annotator
----------------------------------------------------------------------------------------
 */

include { SDRF_AGENTIC_ANNOTATOR } from './workflows/sdrf_agentic_annotator'
include { PIPELINE_INITIALISATION ; PIPELINE_COMPLETION } from './subworkflows/local/utils_sdrf_agent'

workflow {

    main:
    PIPELINE_INITIALISATION(params.input)
    SDRF_AGENTIC_ANNOTATOR(PIPELINE_INITIALISATION.out.samplesheet)
    PIPELINE_COMPLETION(SDRF_AGENTIC_ANNOTATOR.out.summary, SDRF_AGENTIC_ANNOTATOR.out.verdicts)

    publish:
    summary = SDRF_AGENTIC_ANNOTATOR.out.summary
    annotated = SDRF_AGENTIC_ANNOTATOR.out.annotated
    reviewed = SDRF_AGENTIC_ANNOTATOR.out.reviewed
    revised = SDRF_AGENTIC_ANNOTATOR.out.revised
    revised_review = SDRF_AGENTIC_ANNOTATOR.out.revised_review
    coverage = SDRF_AGENTIC_ANNOTATOR.out.coverage
    refine_decision = SDRF_AGENTIC_ANNOTATOR.out.refine_decision
    refine_verdict = SDRF_AGENTIC_ANNOTATOR.out.refine_verdict
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
