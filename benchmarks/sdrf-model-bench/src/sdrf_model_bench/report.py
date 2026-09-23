"""Aggregate scored runs into a per-model summary and render the workshop slide + backup plots.

Encoding is fixed across every panel: raw arm = categorical slot 1 (blue), skills arm = slot 2
(orange), both validated for colour-vision deficiency on the light and dark surfaces. Magnitude
tables use a single-hue sequential ramp so they never borrow the arm colours.
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402

QTYPES = ("TMT", "LFQ", "DIA")
TIERS = ("rich", "poor")
COMPONENTS = (("validity", 20), ("completeness", 15), ("accuracy", 50), ("specificity", 15))
WARN_FLAGS = ("failed", "context_limited", "leak_suspect", "contamination_suspect")
DOLLAR_TICKS = {0.003: "$0.003", 0.01: "$0.01", 0.03: "$0.03", 0.1: "$0.10", 0.3: "$0.30",
                1: "$1", 3: "$3", 10: "$10", 30: "$30"}
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e6e5e1",
        "raw": "#2a78d6", "skills": "#eb6834",
        "slots": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
        "ramp": ["#f0efec", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "grid": "#383835",
        "raw": "#3987e5", "skills": "#d95926",
        "slots": ["#3987e5", "#d95926", "#199e70", "#c98500"],
        "ramp": ["#383835", "#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#3987e5", "#6da7ec"],
    },
}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _sem(xs):
    return statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0


def _dataset_means(recs, key="headline"):
    """Average replicates and manuscript conditions within a dataset first: n = datasets."""
    per_ds = defaultdict(list)
    for r in recs:
        if r.get(key) is not None:
            per_ds[r["accession"]].append(r[key])
    return [statistics.fmean(v) for v in per_ds.values()]


TRIAGE_CLASSES = ("match", "style", "accession_conflict", "run_wrong", "curated_richer",
                  "curated_wrong", "curated_unscorable", "run_richer")


def _triage_shares(recs) -> dict[str, float]:
    total = Counter()
    for r in recs:
        total.update(r.get("triage") or {})
    n = sum(total.values())
    return {c: (total[c] / n if n else 0.0) for c in TRIAGE_CLASSES}


def _rate(recs, key: str) -> float | None:
    tot = sum((r.get("accessions") or {}).get("total", 0) for r in recs)
    return (sum((r.get("accessions") or {}).get(key, 0) for r in recs) / tot) if tot else None


def summarise(records: list[dict]) -> list[dict]:
    by_model = defaultdict(list)
    for r in records:
        by_model[r["model_id"]].append(r)
    rows = []
    for model_id, recs in by_model.items():
        ds = _dataset_means(recs)
        deltas = []
        for acc in {r["accession"] for r in recs}:
            on = [r["headline"] for r in recs if r["accession"] == acc and r["manuscript"]]
            off = [r["headline"] for r in recs if r["accession"] == acc and not r["manuscript"]]
            if on and off:
                deltas.append(statistics.fmean(on) - statistics.fmean(off))
        costs = [r.get("cost_usd") for r in recs]
        rows.append({
            "model_id": model_id,
            "arm": recs[0].get("arm", "raw"),
            "provider": recs[0].get("provider", ""),
            "base": (recs[0].get("model") or model_id) + (" (thinking)" if recs[0].get("think") else ""),
            "n": len(ds),
            "runs": len(recs),
            "judged": sum(r.get("judge") is not None for r in recs),
            "headline": statistics.fmean(ds) if ds else 0.0,
            "headline_sem": _sem(ds),
            "deterministic": _mean(_dataset_means(recs, "deterministic")),
            "judge": _mean(_dataset_means(recs, "judge")),
            "components": {c: _mean(r.get(c) for r in recs) for c, _ in COMPONENTS},
            "tokens": statistics.fmean(sum((r.get("usage") or {}).get(k, 0) for k in TOKEN_KEYS) for r in recs),
            "cost_usd": _mean(costs) if any(c is not None for c in costs) else None,
            "minutes": (_mean(r.get("wall_s") for r in recs) or 0.0) / 60,
            "by_qtype": {q: _mean(_dataset_means([r for r in recs if r.get("qtype") == q])) for q in QTYPES},
            "by_tier": {t: _mean(_dataset_means([r for r in recs if r.get("tier") == t])) for t in TIERS},
            "ms_delta": statistics.fmean(deltas) if deltas else None,
            "flags": dict(Counter(f for r in recs for f in r.get("flags", []))),
            # triage (bigbio/sdrf-skills PR #24's classes, by rule): share of scored cells per class
            "triage": _triage_shares(recs),
            "accession_malformed_rate": _rate(recs, "malformed"),
            "accession_verified_rate": _rate(recs, "verified"),
            "template_self_declared": _mean(float(bool(r.get("template_self_declared"))) for r in recs),
            "reference_defect_runs": sum(1 for r in recs if r.get("reference_defects")),
        })
    return sorted(rows, key=lambda r: -r["headline"])


def _luminance(rgb) -> float:
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _best_ink(rgb) -> str:
    """Near-black or white, whichever has the higher WCAG contrast against the fill."""
    fill = _luminance(rgb)
    return "#0b0b0b" if (fill + 0.05) / (_luminance((0.043,) * 3) + 0.05) >= 1.05 / (fill + 0.05) else "#ffffff"


# ---------------------------------------------------------------- labels and colours

FRIENDLY = {
    "claude-opus-5": "Opus 5", "claude-sonnet-5": "Sonnet 5", "claude-haiku-4-5": "Haiku 4.5",
    "gemma4:12b": "gemma4 12B", "gemma2:9b": "gemma2 9B", "qwen2.5:3b": "qwen2.5 3B", "qwen3:4b": "qwen3 4B",
}
# One colour per kind of configuration, in the palette's fixed categorical order (validated for CVD).
FAMILIES = [("claude", "Claude, prompt only"), ("skills", "Claude + SDRF skills"),
            ("local", "Local model (Ollama)"), ("other", "Other model")]


def family(row: dict) -> str:
    if row.get("arm") == "skills":
        return "skills"
    provider = row.get("provider") or ""
    if provider in ("claude-cli", "anthropic"):
        return "claude"
    return "local" if provider == "ollama" else "other"


def config_label(row: dict) -> str:
    base = row["base"]
    thinking = base.endswith(" (thinking)")
    model = base.removesuffix(" (thinking)")
    name = FRIENDLY.get(model, model)
    kind = family(row)
    if kind == "skills":
        return f"{name} + SDRF skills"
    if kind == "claude":
        return f"{name} (prompt only)"
    if kind == "local":
        return f"{name} · thinking (local)" if thinking else f"{name} (local)"
    return name


def _colors(t) -> dict:
    return dict(zip([k for k, _ in FAMILIES], t["slots"]))


def _cost_text(row) -> str:
    if row["cost_usd"] is not None:
        return f"${row['cost_usd']:.2f} · {row['minutes']:.0f} min"
    return f"{row['minutes']:.0f} min on a laptop"


def _warn_text(row) -> str:
    failed = row["flags"].get("failed", 0)
    limited = row["flags"].get("context_limited", 0)
    parts = [f"{failed} failed" if failed else "", f"{limited} over context" if limited else ""]
    return "  ⚠ " + ", ".join(p for p in parts if p) if failed or limited else ""


def _new_fig(t, height=9.0, width=16.0):
    fig = plt.figure(figsize=(width, height), facecolor=t["surface"])
    return fig


def _style(ax, t, grid_axis="x"):
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], labelsize=13, length=0)
    if grid_axis:
        ax.grid(axis=grid_axis, color=t["grid"], linewidth=1)
        ax.set_axisbelow(True)


def _titles(fig, t, title, subtitle, footer=None):
    fig.text(0.03, 0.935, title, fontsize=26, color=t["ink"], weight="bold")
    if subtitle:
        fig.text(0.03, 0.885, subtitle, fontsize=15, color=t["ink2"])
    if footer:
        fig.text(0.03, 0.03, footer, fontsize=11, color=t["ink2"], linespacing=1.5)


def _legend(fig, t, kinds, y=0.80):
    cols = _colors(t)
    handles = [Rectangle((0, 0), 1, 1, color=cols[k]) for k, _ in FAMILIES if k in kinds]
    labels = [lab for k, lab in FAMILIES if k in kinds]
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(0.03, y), ncol=len(labels), frameon=False,
               fontsize=13, labelcolor=t["ink"], handlelength=1.2, columnspacing=2.0)


def _save(fig, path: Path, t, svg=False):
    path = Path(path)
    fig.savefig(path.with_suffix(".png"), dpi=200, facecolor=t["surface"])
    if svg:
        fig.savefig(path.with_suffix(".svg"), facecolor=t["surface"])
    plt.close(fig)


def _rows_in_order(summary):
    return sorted(summary, key=lambda r: -r["headline"])


def _n_datasets(summary):
    return max((r["n"] for r in summary), default=0)


def _present_qtypes(summary):
    return [q for q in QTYPES if any(r["by_qtype"].get(q) is not None for r in summary)]


# ---------------------------------------------------------------- main slide

def render_slide(summary: list[dict], path: Path, theme: str = "light", pending=(),
                 baseline: float | None = None) -> None:
    """One chart, one question: which configuration writes the best SDRF, and what does it cost?"""
    t = THEMES[theme]
    cols = _colors(t)
    rows = _rows_in_order(summary)
    labels = [config_label(r) for r in rows] + [f"{p} (awaiting results)" for p in pending]
    n = len(labels)
    fig = _new_fig(t)  # 16:9
    ax = fig.add_axes([0.28, 0.14, 0.48, 0.61])
    _style(ax, t)
    ys = list(range(n))[::-1]
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.6, n - 0.4)
    beside = blended_transform_factory(ax.transAxes, ax.transData)  # x in axes units, y in rows
    for y, r in zip(ys, rows):
        c = cols[family(r)]
        ax.barh(y, r["headline"], height=0.62, color=c, edgecolor=t["surface"], linewidth=2)
        if r["headline_sem"]:
            ax.plot([r["headline"] - r["headline_sem"], r["headline"] + r["headline_sem"]], [y, y],
                    color=t["ink"], linewidth=1.5, alpha=0.6, solid_capstyle="round")
        ax.text(r["headline"] + r["headline_sem"] + 1.5, y, f"{r['headline']:.0f}", va="center", ha="left",
                fontsize=15, color=t["ink"], weight="bold")
        ax.text(1.03, y, _cost_text(r) + _warn_text(r), transform=beside, va="center", ha="left",
                fontsize=13, color=t["ink2"], clip_on=False)
    for y in ys[len(rows):]:
        ax.barh(y, 100, height=0.62, facecolor="none", edgecolor=t["grid"], linewidth=1.5, linestyle="--")
    if baseline is not None:
        # Everything left of this line is obtainable without reading the evidence, so the bar that
        # matters is the part beyond it. A configuration short of the line is annotating from priors.
        ax.axvline(baseline, color=t["ink2"], linewidth=1.5, linestyle=(0, (5, 4)), alpha=0.8, zorder=3)
        ax.text(baseline - 1.5, n - 0.42, f"reads no evidence: {baseline:.0f}", va="bottom", ha="right",
                fontsize=12, color=t["ink2"], style="italic")
    ax.set_yticks(ys, labels, fontsize=15, color=t["ink"])
    ax.set_xlabel("score (0-100): agreement with the curated SDRF", color=t["ink2"], fontsize=13)
    ax.text(1.03, n - 0.4, "cost per SDRF", transform=beside, va="bottom", ha="left", fontsize=13,
            color=t["ink"], weight="bold", clip_on=False)

    best = rows[0] if rows else None
    title = f"{config_label(best)} writes the most accurate SDRFs" if best else "SDRF annotation quality"
    qt = ", ".join(_present_qtypes(summary))
    nd = _n_datasets(summary)
    subtitle = f"Mean over {nd} dataset{'s' if nd != 1 else ''} ({qt}), each annotated with and without the paper"
    judged = sum(r["judged"] for r in summary)
    runs = sum(r["runs"] for r in summary)
    coverage = "every run" if judged >= runs else f"a balanced subset ({judged} of {runs} runs)"
    _titles(fig, t, title, subtitle,
            footer="Score = 80% deterministic match to the curated SDRF + 20% reference-guided LLM judge, "
                   f"judged on {coverage}. Whiskers: ±1 SEM across datasets.\n"
                   "Cost is the API-equivalent reported by Claude Code.")
    _legend(fig, t, {family(r) for r in rows})
    _save(fig, path, t, svg=True)


# ---------------------------------------------------------------- backup slides

def _paired_chart(summary, t, path, title, subtitle, left_key, right_key, left_label, right_label, footer):
    """Per configuration: a light bar for condition A and a solid bar for condition B."""
    cols = _colors(t)
    rows = _rows_in_order(summary)
    fig = _new_fig(t)
    ax = fig.add_axes([0.28, 0.12, 0.58, 0.63])
    _style(ax, t)
    ys = list(range(len(rows)))[::-1]
    for y, r in zip(ys, rows):
        c = cols[family(r)]
        a, b = left_key(r), right_key(r)
        if a is not None:
            ax.barh(y + 0.19, a, height=0.36, color=c, alpha=0.35, edgecolor=t["surface"], linewidth=2)
            ax.text(a + 1, y + 0.19, f"{a:.0f}", va="center", fontsize=12, color=t["ink2"])
        if b is not None:
            ax.barh(y - 0.19, b, height=0.36, color=c, edgecolor=t["surface"], linewidth=2)
            ax.text(b + 1, y - 0.19, f"{b:.0f}", va="center", fontsize=12, color=t["ink"], weight="bold")
        if a is not None and b is not None:
            ax.text(101, y, f"{b - a:+.0f}", va="center", ha="left", fontsize=14, color=t["ink"], weight="bold")
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_yticks(ys, [config_label(r) for r in rows], fontsize=14, color=t["ink"])
    ax.set_xlabel("score (0-100)", color=t["ink2"], fontsize=13)
    ax.text(1.01, len(rows) - 0.4, "change", transform=blended_transform_factory(ax.transAxes, ax.transData),
            va="bottom", fontsize=13, color=t["ink"], weight="bold", clip_on=False)
    handles = [Rectangle((0, 0), 1, 1, color=t["ink2"], alpha=0.35), Rectangle((0, 0), 1, 1, color=t["ink2"])]
    fig.legend(handles, [left_label, right_label], loc="lower left", bbox_to_anchor=(0.03, 0.80), ncol=2,
               frameon=False, fontsize=13, labelcolor=t["ink"])
    _titles(fig, t, title, subtitle, footer)
    _save(fig, path, t)


def _by_manuscript(recs, on: bool):
    return _mean(_dataset_means([r for r in recs if r["manuscript"] == on]))


def render_backups(records: list[dict], summary: list[dict], outdir: Path, theme: str = "light") -> None:
    t = THEMES[theme]
    outdir = Path(outdir)
    write_summary_tsv(summary, outdir / "summary.tsv")
    by_model = defaultdict(list)
    for r in records:
        by_model[r["model_id"]].append(r)

    # 1. Does the paper help?
    _paired_chart(summary, t, outdir / "backup_1_manuscript",
                  "Does giving the model the paper help?",
                  "Same datasets, annotated from PRIDE metadata alone and again with the paper's Methods section",
                  lambda r: _by_manuscript(by_model[r["model_id"]], False),
                  lambda r: _by_manuscript(by_model[r["model_id"]], True),
                  "without the paper", "with the paper",
                  "Change = with minus without, averaged per dataset.")

    # 3. Does better PRIDE metadata help?
    _paired_chart(summary, t, outdir / "backup_3_pride_metadata",
                  "Do richer PRIDE records give better SDRFs?",
                  "Datasets split by how complete their PRIDE metadata is (relative to this pool)",
                  lambda r: r["by_tier"].get("poor"), lambda r: r["by_tier"].get("rich"),
                  "sparse PRIDE record", "rich PRIDE record",
                  "Rich/sparse = top/bottom third of PRIDE fields filled (organism, tissue, disease, instrument, PTMs, "
                  "quantification, protocols).")

    # 2. Which experiment types are hardest? Small multiples, one panel per quantification type.
    cols = _colors(t)
    rows = _rows_in_order(summary)
    qts = _present_qtypes(summary) or list(QTYPES)
    fig = _new_fig(t)
    left, width, gap = 0.28, 0.68 / len(qts), 0.03
    ys = list(range(len(rows)))[::-1]
    for i, q in enumerate(qts):
        ax = fig.add_axes([left + i * width, 0.10, width - gap, 0.62])
        _style(ax, t)
        for y, r in zip(ys, rows):
            v = r["by_qtype"].get(q)
            if v is None:
                continue
            ax.barh(y, v, height=0.62, color=cols[family(r)], edgecolor=t["surface"], linewidth=2)
            ax.text(v + 2, y, f"{v:.0f}", va="center", fontsize=12, color=t["ink"])
        ax.set_xlim(0, 100)
        ax.set_xticks([0, 50, 100])
        ax.set_ylim(-0.6, len(rows) - 0.4)
        ax.set_title(q, fontsize=17, color=t["ink"], weight="bold", loc="left")
        if i == 0:
            ax.set_yticks(ys, [config_label(r) for r in rows], fontsize=14, color=t["ink"])
        else:
            ax.set_yticks([])
    _titles(fig, t, "Which experiment types are hardest to annotate?",
            "Score by quantification strategy (each panel is an average over its datasets)",
            "TMT rows are one per file and channel, so TMT SDRFs are longer and the design is harder to encode.")
    _legend(fig, t, {family(r) for r in rows})
    _save(fig, outdir / "backup_2_quant_type", t)

    # 4. Where do the points come from? Stacked weighted components.
    fig = _new_fig(t)
    ax = fig.add_axes([0.28, 0.12, 0.66, 0.62])
    _style(ax, t)
    comp_names = {"validity": "valid file", "completeness": "columns & rows present",
                  "accuracy": "correct values", "specificity": "no needless 'not available'"}
    left_edge = [0.0] * len(rows)
    for (comp, weight), color in zip(COMPONENTS, [t["ramp"][i] for i in (1, 3, 5, 7)]):
        vals = [(r["components"][comp] or 0) * weight * 0.8 for r in rows]
        ax.barh(ys, vals, left=left_edge, height=0.62, color=color, edgecolor=t["surface"], linewidth=2,
                label=f"{comp_names[comp]} (max {weight * 0.8:.0f})")
        for y, lft, v in zip(ys, left_edge, vals):
            if v >= 6:
                ax.text(lft + v / 2, y, f"{v:.0f}", va="center", ha="center", fontsize=11, color=_best_ink(to_rgb(color)))
        left_edge = [a + b for a, b in zip(left_edge, vals)]
    ax.set_xlim(0, 80)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_yticks(ys, [config_label(r) for r in rows], fontsize=14, color=t["ink"])
    ax.set_xlabel("points out of the 80 deterministic points", color=t["ink2"], fontsize=13)
    fig.legend(*ax.get_legend_handles_labels(), loc="lower left", bbox_to_anchor=(0.03, 0.80), ncol=4,
               frameon=False, fontsize=12.5, labelcolor=t["ink"])
    _titles(fig, t, "Where do the points come from?",
            "The deterministic 80% of the score, split into its four parts", None)
    _save(fig, outdir / "backup_4_components", t)

    # 5. Quality vs cost (Claude configurations; local models have no dollar cost).
    priced = [r for r in rows if r["cost_usd"]]
    fig = _new_fig(t)
    ax = fig.add_axes([0.10, 0.12, 0.84, 0.63])
    _style(ax, t, grid_axis="both")
    for r in priced:
        ax.scatter(r["cost_usd"], r["headline"], s=260, color=cols[family(r)], edgecolors=t["surface"],
                   linewidths=2, zorder=3)
        ax.annotate(config_label(r), (r["cost_usd"], r["headline"]), xytext=(12, 0), textcoords="offset points",
                    va="center", fontsize=13, color=t["ink"])
    if priced:
        ax.set_xscale("log")
        lo, hi = min(r["cost_usd"] for r in priced), max(r["cost_usd"] for r in priced)
        ax.set_xlim(lo / 2, hi * 4)
        ticks = [v for v in DOLLAR_TICKS if lo / 2 <= v <= hi * 4]
        ax.set_xticks(ticks, [DOLLAR_TICKS[v] for v in ticks])
        ax.minorticks_off()
    ax.set_ylim(0, 100)
    ax.set_xlabel("API-equivalent cost per SDRF (US$, log scale)", color=t["ink2"], fontsize=13)
    ax.set_ylabel("score (0-100)", color=t["ink2"], fontsize=13)
    _titles(fig, t, "What does quality cost?", "Claude configurations; up and to the left is better", None)
    _legend(fig, t, {family(r) for r in priced})
    _save(fig, outdir / "backup_5_cost_vs_quality", t)

    # 6. Does the judge agree with the deterministic score? (only when the judge ran)
    pairs = [(r["deterministic"], r["judge"], family(r)) for r in records if r.get("judge") is not None]
    if len(pairs) >= 3:
        fig = _new_fig(t)
        ax = fig.add_axes([0.30, 0.12, 0.40, 0.63])
        _style(ax, t, grid_axis="both")
        for fam in {p[2] for p in pairs}:
            pts = [(d, j) for d, j, f in pairs if f == fam]
            ax.scatter(*zip(*pts), s=70, color=cols[fam], edgecolors=t["surface"], linewidths=1.5, alpha=0.85)
        ax.plot([0, 100], [0, 100], color=t["ink2"], linewidth=1, linestyle="--")
        xs, js = [p[0] for p in pairs], [p[1] for p in pairs]
        r_val = statistics.correlation(xs, js) if len(set(xs)) > 1 and len(set(js)) > 1 else float("nan")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_xlabel("deterministic score", color=t["ink2"], fontsize=13)
        ax.set_ylabel("LLM judge score", color=t["ink2"], fontsize=13)
        _titles(fig, t, "Does the LLM judge agree?", f"One dot per SDRF · Pearson r = {r_val:.2f} (n = {len(pairs)})")
        _save(fig, outdir / "backup_6_judge_agreement", t)

    # 7. Where do the disagreements with the curated reference come from? (PR #24's triage classes)
    rows = _rows_in_order(summary)
    fig = _new_fig(t)
    ax = fig.add_axes([0.28, 0.12, 0.58, 0.63])
    _style(ax, t)
    ys = list(range(len(rows)))[::-1]
    shades = {"match": t["ink2"], "style": "#9ecae1", "accession_conflict": "#fdd0a2", "run_wrong": "#e6550d",
              "curated_richer": "#fdae6b", "curated_wrong": "#a1d99b", "curated_unscorable": "#d9d9d9",
              "run_richer": "#c7e9c0"}
    for y, r in zip(ys, rows):
        left = 0.0
        for c in TRIAGE_CLASSES:
            w = 100 * r["triage"].get(c, 0.0)
            if w:
                ax.barh(y, w, left=left, height=0.62, color=shades[c], edgecolor=t["surface"], linewidth=1)
                left += w
    ax.set_yticks(ys)
    ax.set_yticklabels([config_label(r) for r in rows], fontsize=13, color=t["ink"])
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of scored cells (%)", fontsize=12, color=t["ink2"])
    _titles(fig, t, "What kind of disagreement is it?",
            "Each scored cell classified against the curated reference: correct, style-only, wrong, or the reference's fault",
            "style = right term, accession on one side only (not penalised). curated_wrong = reference cell malformed. "
            "unscorable = ppm vs Da or malformed reference with a different label (excluded). run_richer = value where the "
            "reference has none (excluded; cannot be verified offline).")
    _save(fig, outdir / "backup_7_triage", t)



def write_summary_tsv(summary: list[dict], path: Path) -> None:
    cols = ["model_id", "arm", "base", "n", "runs", "headline", "headline_sem", "deterministic", "judge",
            "tokens", "cost_usd", "minutes", "ms_delta"]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols + [f"{q}" for q in QTYPES] + [f"tier_{t}" for t in TIERS]
                   + [c for c, _ in COMPONENTS] + ["flags"])
        for r in summary:
            w.writerow([r[c] for c in cols] + [r["by_qtype"][q] for q in QTYPES]
                       + [r["by_tier"][t] for t in TIERS] + [r["components"][c] for c, _ in COMPONENTS]
                       + [";".join(f"{k}={v}" for k, v in sorted(r["flags"].items()))])
