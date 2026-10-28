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
    PIPELINE_COMPLETION(SDRF_AGENTIC_ANNOTATOR.out.summary)

    publish:
    summary = SDRF_AGENTIC_ANNOTATOR.out.summary
    annotated = SDRF_AGENTIC_ANNOTATOR.out.annotated
    reviewed = SDRF_AGENTIC_ANNOTATOR.out.reviewed
    revised = SDRF_AGENTIC_ANNOTATOR.out.revised
    revised_review = SDRF_AGENTIC_ANNOTATOR.out.revised_review
    coverage = SDRF_AGENTIC_ANNOTATOR.out.coverage
    final_sdrf = SDRF_AGENTIC_ANNOTATOR.out.final_sdrf
    refine_decision = SDRF_AGENTIC_ANNOTATOR.out.refine_decision
    refine_verdict = SDRF_AGENTIC_ANNOTATOR.out.refine_verdict
    versions = SDRF_AGENTIC_ANNOTATOR.out.versions
}
output {
    annotated {
        path { r ->
            r.sdrf >> "${r.pxd}/${r.sdrf.name}"
            r.manifest >> "${r.pxd}/${r.manifest.name}"
            r.validation >> "${r.pxd}/${r.validation.name}"
            r.report >> "${r.pxd}/${r.report.name}"
            r.samples >> "${r.pxd}/${r.samples.name}"
            r.technical >> "${r.pxd}/${r.technical.name}"
            r.evidence >> "${r.pxd}/${r.evidence.name}"
        }
    }
    reviewed {
        path { r -> r.review >> "${r.pxd}/${r.review.name}" }
    }
    coverage {
        path { r -> r.coverage >> "${r.pxd}/${r.coverage.name}" }
    }
    // the passing SDRF with the pipeline in its annotation tool column, validated with parse_sdrf
    final_sdrf {
        path { r ->
            r.sdrf >> "${r.pxd}/final/${r.sdrf.name}"
            r.validation >> "${r.pxd}/final/${r.validation.name}"
        }
    }
    // revise round 1 in <pxd>/revised/, round 2 in <pxd>/revised_2/
    revised {
        path { r ->
            r.sdrf >> "${r.pxd}/${r.dir}/${r.sdrf.name}"
            r.manifest >> "${r.pxd}/${r.dir}/${r.manifest.name}"
            r.validation >> "${r.pxd}/${r.dir}/${r.validation.name}"
            r.report >> "${r.pxd}/${r.dir}/${r.report.name}"
            r.samples >> "${r.pxd}/${r.dir}/${r.samples.name}"
            r.technical >> "${r.pxd}/${r.dir}/${r.technical.name}"
        }
    }
    revised_review {
        path { r ->
            r.review >> "${r.pxd}/${r.dir}/${r.review.name}"
            r.coverage >> "${r.pxd}/${r.dir}/${r.coverage.name}"
        }
    }
    summary {
        path '.'
    }
    // the chosen SDRF (refined or existing) with its evidence manifest, review and coverage report
    refine_decision {
        path { r ->
            r.sdrf >> "${r.pxd}/${r.pxd}.sdrf.tsv"
            r.manifest >> "${r.pxd}/${r.pxd}.evidence.json"
            r.review >> "${r.pxd}/${r.pxd}.review.json"
            r.coverage >> "${r.pxd}/${r.pxd}.coverage.json"
        }
    }
    refine_verdict {
        path { r -> r.verdict >> "${r.pxd}/${r.verdict.name}" }
    }
    versions {
        path 'pipeline_info'
    }
}
