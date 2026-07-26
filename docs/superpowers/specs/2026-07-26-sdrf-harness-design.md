# SDRF Annotation Harness — Design Spec

**Date:** 2026-07-26
**Status:** Approved design, pre-implementation
**Location:** `sdrf-workspace/sdrf-harness/` (independent package, separate from the `sdrf-annotated-datasets` corpus repo)

## 1. Goal

Scale SDRF annotation of public proteomics datasets toward **~10,000** (≈ 1/3 of PRIDE), contributing to the shared `datasets/bulk-lfq-dia-small` branch, by moving bulk work off expensive Claude-agent reasoning and onto a **tiered pipeline**: deterministic engineering does most of it, a **local GPU-served LLM** fills semantic gaps, and **Claude** handles only escalations and QA.

Success = high auto-merge rate, low Claude-escalation rate, and no regression against a golden set of hand-annotated datasets — at a throughput that makes 10k realistic.

## 2. Constraints & locked decisions

- **Infra (bulk tier):** a GPU box running a served open model (vLLM / Ollama / llama.cpp) hosting an open LLM (e.g. Qwen/Llama 8B–70B). Claude Code is the refinement tier.
- **Quality gate — deterministic + confidence-routed:** `parse_sdrf validate-sdrf` + coordinate-collision + ragged-row + ontology-integrity checks are the **hard gate**. The local model emits a self-confidence score. Only **low-confidence OR gate-failing** datasets escalate to Claude; **high-confidence + passing auto-merge**.
- **Selection — throughput / easiest-first:** rank candidates by *annotatability*. v1 targets single-organism **LFQ-DDA and DIA** with clean deposited metadata. **TMT/iTRAQ deferred** (isobaric channel→sample maps add complexity). MassIVE first, then PRIDE.
- **Approach A — deterministic-first, LLM-as-fallback:** file-gathering and technical-column assembly are pure engineering (deterministic, cacheable, testable). The local LLM is called **only for the semantic residue** (sample↔file structure, biological characteristics). Claude is called **only for escalations**. Most datasets need no LLM at all.
- **Hard constraint carried from the corpus rules:** vendor-native raw files only (`.raw`/`.wiff`/`.d`/`.raw.gz`/`.wiff.gz`); reject peak-list-only deposits. Never use pandas `to_csv` for SDRF (duplicate-header corruption).

## 3. Architecture — pipeline spine

A queue-driven pipeline. A shared **work ledger** (SQLite) is the single source of truth for each dataset's status, so the two existing annotation AIs *and* N pipeline workers all claim from the same queue — structurally eliminating duplicate work and write-collisions.

Per-dataset stages:

1. **Harvest** *(deterministic, batch)* — enumerate candidate accessions from MassIVE + PRIDE (local dumps + APIs), compute `annotatability` score, insert as `candidate`. v1 filters: vendor-native files present; acquisition ∈ {LFQ-DDA, DIA}; single-organism; not TMT/iTRAQ; metadata present.
2. **Claim** *(atomic)* — a worker leases the top-scored `candidate` rows → `claimed` (worker id + lease TTL).
3. **Fetch** *(deterministic)* — file list + any deposited SDRF / experimental-design / sample table + protocol/instrument/organism; cache to disk. **A deposited SDRF short-circuits to validate + light enrich.**
4. **Assemble-technical** *(deterministic)* — build run-parameter columns from metadata via the `cvmaps` library (instrument→MS, enzyme→MS, mods→UNIMOD, tolerances, label). Emits a **partial SDRF + a gap list**.
5. **Draft-semantic** *(LOCAL LLM — only if gaps)* — filenames + condition labels + description → schema-constrained JSON: sample↔file map (biological/technical replicate, fraction) + organism-part/cell-type/disease/treatment proposals, each with **evidence + a confidence score**.
6. **Ground** *(deterministic)* — resolve proposed ontology terms against the local OLS cache; unresolvable terms are flagged and lower confidence.
7. **Validate** *(deterministic gate)* — `parse_sdrf` + collision + ragged + ontology-integrity → verdict + reasons.
8. **Route** — pass & confidence ≥ threshold → `ready`; pass & low-confidence, or fail → `escalate`.
9. **Refine** *(CLAUDE — only escalations)* — fix/annotate, re-validate → `ready`; the before/after diff is logged as a training signal.
10. **Merge** *(deterministic)* — batched commit (~25 datasets) to the branch → `merged`, release claim.
11. **Feedback** *(periodic)* — mine Claude's fixes + failures → update `cvmaps`, ontology aliases, and the local-model few-shot bank.

## 4. Components

All under `sdrf-workspace/sdrf-harness/`. Each is an independent, unit-testable module with a typed record interface; only `drafter` and `refiner` call a model.

| Module | One job | Input → Output | LLM |
|---|---|---|---|
| `ledger/` | state + atomic claims (SQLite) | status transitions, leases | — |
| `harvester/` | enumerate + score candidates | dumps/APIs → `candidate` rows | — |
| `fetcher/` | accession → cached metadata bundle | files, deposited SDRF, protocol | — |
| `cvmaps/` | versioned lookups | instrument→MS, enzyme→MS, mod→UNIMOD, ontology aliases | — |
| `assembler/` | technical SDRF + gap list | bundle → partial SDRF | — |
| `drafter/` | semantic JSON for gaps | context → sample-map + characteristics + confidence | **local** |
| `grounder/` | verify terms vs ontology cache | proposals → grounded/flagged | — |
| `validator/` | the hard gate | SDRF → verdict + confidence + reasons | — |
| `router/` | thresholds → ready/escalate | verdict → route | — |
| `refiner/` | escalation handler | bundle+draft → fixed SDRF | **Claude** |
| `merger/` | batched commit to branch | ready → `merged` | — |
| `orchestrator/` | pull claimed work through stages, retries/leases | — | — |
| `feedback/` | mine Claude diffs → map/prompt updates | escalations → updated cvmaps + few-shot bank | — |

## 5. Data contracts

**Ledger row (SQLite `datasets` table):** `accession` (PK), `repository` (pride|massive), `status` (candidate|claimed|fetched|drafted|validated|ready|escalate|merged|blocked), `annotatability` (float), `worker_id`, `lease_expires_at`, `content_hash`, `confidence` (float), `block_reason`, `route`, timestamps.

**Metadata bundle (JSON, per accession, cached):** `accession`, `repository`, `organism(s)` (name + NCBITaxon), `instrument(s)`, `protocol` (enzyme/mods/tolerances/acquisition), `files` (name, ext, size), `deposited_sdrf` (path|null), `design_tables` (paths), `labels` (condition strings), `gaps` (list of unfilled columns). This is the spine every module reads/writes; the assembler produces it, the drafter/grounder enrich it.

## 6. Coordination (multi-writer)

The ledger is authoritative. Claims are leases with a TTL → a crashed worker's datasets auto-free. Exclusive claims mean no two workers touch the same accession; since each writes only its claimed dataset dirs, batched commits never path-conflict. The `merger` pulls/rebases before pushing. The two existing annotation AIs join as **workers claiming from the same ledger** (the mechanism that ends the manual collision-avoidance we have been doing by hand).

## 7. Error handling

- **Idempotency:** every stage keyed by `accession` + `content_hash`; safe to re-run.
- **Poison datasets:** max-retry → `blocked` with a structured reason (the deferred pile, now queryable).
- **Escalation-budget cap:** if Claude escalation rate exceeds a threshold, harvest pauses and signals "local prompts/maps need work" — the feedback loop, not silent cost blowup.
- **Lease expiry** frees stuck claims for re-processing.

## 8. Testing

- **Golden regression set:** the ~130 datasets already hand-annotated (cross-species orthologues, PeptideAtlas pathogens, PaxDb). The pipeline must reproduce them within tolerance (organism, key characteristics, 0 collisions, validation pass).
- **Per-module unit tests** with cached fixtures — no live network in tests.
- **`--dry-run`** mode stops before merge for inspection.

## 9. Phased rollout (each phase ships value alone)

- **Phase 0 — deterministic spine, zero LLM:** `ledger + harvester + fetcher + assembler + validator + merger`. Annotates deposited-SDRF datasets and clean single-organism LFQ/DIA. Proven against the golden set.
- **Phase 1 — `drafter + grounder + router`:** local GPU fills semantic gaps; confidence routing begins.
- **Phase 2 — `refiner` + `feedback`:** Claude escalations + the learning loop.
- **Pilot gate:** 100 MassIVE LFQ/DIA single-organism datasets; measure auto-merge %, escalation %, golden-set fidelity, throughput; then scale toward 10k.

## 10. Metrics

Throughput (datasets/day), auto-merge rate, Claude-escalation rate, validation-fail rate, golden-set fidelity, blocked-rate + reasons.

## 11. Out of scope (v1)

TMT/iTRAQ isobaric datasets (channel→sample maps); peak-list-only deposits; multi-organism datasets requiring per-file organism resolution; datasets with no recoverable sample metadata. All are captured as `blocked` with a reason for a later phase.
