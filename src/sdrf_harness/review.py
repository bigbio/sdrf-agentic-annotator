from __future__ import annotations
import glob, os, sys
from .validator import full_report, load_ontology_labels

def review_dir(root, labels=None, run_cli=False) -> dict:
    root = str(root)
    files = sorted(glob.glob(os.path.join(root, "**", "*.sdrf.tsv"), recursive=True))
    passed = 0; failed = []
    for f in files:
        r = full_report(f, labels=labels, run_cli=run_cli)
        if r.passed:
            passed += 1
        else:
            failed.append((os.path.relpath(f, root), r))
    return {"total": len(files), "passed": passed, "failed": failed}

def format_report(result) -> str:
    lines = [f"{result['passed']}/{result['total']} passed, {len(result['failed'])} with defects"]
    for rel, r in result["failed"]:
        bits = []
        if r.collisions:
            bits.append(f"{r.collisions} collisions")
        if r.ragged:
            bits.append(f"{r.ragged} ragged")
        if r.accession_mismatches:
            bits.append(f"{len(r.accession_mismatches)} bad accessions "
                        f"(e.g. {r.accession_mismatches[0][0]}={r.accession_mismatches[0][1]})")
        if r.cli_errors:
            bits.append("parse_sdrf error")
        lines.append(f"  {rel}: " + "; ".join(bits))
    return "\n".join(lines)

def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    run_cli = "--cli" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        print("usage: python -m sdrf_harness.review <dir> [--cli]"); return 2
    labels = load_ontology_labels()
    result = review_dir(paths[0], labels=labels, run_cli=run_cli)
    print(format_report(result))
    return 0 if not result["failed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
