# Submitting results without our runner

If your model can't easily be called from `sdrf-bench run` (for example it sits behind an internal
platform), you can generate the SDRFs any way you like and send us the files. We score every
submission with the same scorer and judge.

## Rules

1. **Use only the frozen inputs.** For each dataset, the model may see `data/evidence/<PXD>/pride.json`
   and `files.json`. In the `ms-on` condition it may also see `manuscript.txt`. Give it no web
   access, no retrieval, and no other files.
2. **Use our prompt.** `uv run sdrf-bench prompt --manuscript on > prompts-on.json` (and again with
   `--manuscript off`) writes the exact messages and the output-token budget for every run. Send
   those messages unchanged. You may run up to 2 repair turns in which you return the
   `parse_sdrf validate-sdrf` errors to the model.
3. **Never show the model `data/truth/`.**
4. **Report usage honestly.** Give the tokens as the provider billed them, and the wall-clock time.

## Folder layout

```
outputs/<your-model-id>/<PXD>__ms-on__r1/sdrf.tsv
outputs/<your-model-id>/<PXD>__ms-on__r1/usage.json
outputs/<your-model-id>/<PXD>__ms-off__r1/sdrf.tsv
outputs/<your-model-id>/<PXD>__ms-off__r1/usage.json
... one pair per dataset in data/manifest.tsv (24 folders)
```

`usage.json`:

```json
{
  "model_id": "your-model-id",
  "provider": "custom",
  "model": "your-model-name-and-version",
  "arm": "raw",
  "context_window": 128000,
  "usage": {"input_tokens": 12345, "output_tokens": 2345},
  "cost_usd": null,
  "wall_s": 42.0,
  "flags": []
}
```

- If the model produced nothing usable, leave `sdrf.tsv` out and put `"failed"` in `flags`.
- `cost_usd` is optional. Leave it `null` for local models; the slide then shows minutes instead.

## Check before sending

```bash
uv run sdrf-bench score --outputs outputs --no-judge --out results/check.jsonl
```

Every folder should score without errors. Then zip `outputs/<your-model-id>/` and send it to us.
