# Pablo Moreno: sdrf-skills on open models (PXD008012)

`scorecard.tsv` is Pablo Moreno's scorecard **as he reported it**: three open-weight models running
the sdrf-skills workflow (`samples.tsv` + `technical.tsv` -> `sdrf-tools build`) on PXD008012. The
token counts marked cached/fresh are rounded as reported.

- **Reference:** his scores were computed against the PXD008012 SDRF in sdrf-annotated-datasets
  *before* the 2026-09-24 correction (commit `ec76d5224`). `data-ext/truth/PXD008012.reference.tsv`
  is that same version, so our own runs on PXD008012 are scored against the reference he used.
- **Not re-scored:** his SDRF files are not available, so his scores cannot be re-scored with this
  benchmark's rubric. Figures show them as "reported", never on the same axis as our scores.
- **Row count:** PRIDE lists 143 raw files, and the reference covers 141 of them; his "143-row
  mapping" includes the two files the reference leaves out.
