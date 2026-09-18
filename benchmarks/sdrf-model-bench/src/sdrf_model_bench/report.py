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
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

QTYPES = ("TMT", "LFQ", "DIA")
TIERS = ("rich", "poor")
COMPONENTS = (("validity", 20), ("completeness", 15), ("accuracy", 50), ("specificity", 15))
WARN_FLAGS = ("failed", "context_limited", "leak_suspect", "contamination_suspect")
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
            "base": (recs[0].get("model") or model_id) + (" (thinking)" if recs[0].get("think") else ""),
            "n": len(ds),
            "runs": len(recs),
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
        })
    return sorted(rows, key=lambda r: -r["headline"])


def display_name(base: str) -> str:
    return base.removeprefix("claude-").replace("-4-5", "-4.5")


def _group_by_base(summary):
    groups: dict[str, dict] = {}
    for row in summary:
        groups.setdefault(row["base"], {})[row["arm"]] = row
    best = {b: max(r["headline"] for r in arms.values()) for b, arms in groups.items()}
    return [(b, groups[b]) for b in sorted(groups, key=lambda b: -best[b])]


def _luminance(rgb) -> float:
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _best_ink(rgb) -> str:
    """Near-black or white, whichever has the higher WCAG contrast against the cell."""
    cell = _luminance(rgb)
    return "#0b0b0b" if (cell + 0.05) / (_luminance((0.043,) * 3) + 0.05) >= 1.05 / (cell + 0.05) else "#ffffff"


def _style(ax, t, grid_axis="x"):
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], labelsize=12, length=0)
    if grid_axis:
        ax.grid(axis=grid_axis, color=t["grid"], linewidth=1)
        ax.set_axisbelow(True)


def _cost_line(row) -> str:
    if row is None:
        return ""
    tok = f"{row['tokens'] / 1000:.0f}k tok"
    spend = f"${row['cost_usd']:.2f}" if row["cost_usd"] is not None else f"{row['minutes']:.1f} min"
    warn = sum(row["flags"].get(f, 0) for f in ("failed", "context_limited"))
    return f"{row['arm']:<6} {spend} · {tok}" + (f"  ⚠{warn}" if warn else "")


def render_slide(summary: list[dict], path: Path, theme: str = "light", pending=()) -> None:
    t = THEMES[theme]
    groups = _group_by_base(summary)
    names = [display_name(b) for b, _ in groups] + [f"{p}\n(pending)" for p in pending]
    n_rows = len(names)
    ys = list(range(n_rows - 1, -1, -1))

    fig = plt.figure(figsize=(16, 9), facecolor=t["surface"])
    gs = fig.add_gridspec(1, 4, width_ratios=[3.0, 1.35, 1.25, 1.25], left=0.13, right=0.975,
                          top=0.79, bottom=0.14, wspace=0.12)
    ax, ax_cost, ax_q, ax_ms = (fig.add_subplot(gs[0, i]) for i in range(4))

    # Left: dumbbell raw -> skills, +-1 SEM whiskers, score labels on the dots.
    _style(ax, t)
    for y, (base, arms) in zip(ys, groups):
        raw, skills = arms.get("raw"), arms.get("skills")
        if raw and skills:
            ax.plot([raw["headline"], skills["headline"]], [y, y], color=t["ink2"], linewidth=2,
                    solid_capstyle="round", zorder=1)
        for arm, row, dy in (("raw", raw, -0.28), ("skills", skills, 0.28)):
            if not row:
                continue
            x = row["headline"]
            ax.plot([x - row["headline_sem"], x + row["headline_sem"]], [y, y], color=t[arm],
                    linewidth=4, alpha=0.35, solid_capstyle="round", zorder=2)
            ax.scatter([x], [y], s=150, color=t[arm], edgecolors=t["surface"], linewidths=2, zorder=3)
            ax.text(x, y + dy, f"{x:.0f}", ha="center", va="center", fontsize=12, color=t["ink"], zorder=4)
    for y in ys[len(groups):]:
        ax.scatter([50], [y], s=150, facecolors="none", edgecolors=t["ink2"], linewidths=1.5, linestyle="--")
    ax.set_xlim(-3, 100)  # room for a score of 0
    ax.set_ylim(-0.7, n_rows - 0.3)
    ax.set_yticks(ys, names, fontsize=15, color=t["ink"])
    ax.set_xlabel("score (0-100)", color=t["ink2"], fontsize=12)
    ax.set_title("raw prompt  vs  with SDRF skills", loc="left", color=t["ink"], fontsize=14, pad=10)
    handles = [Line2D([], [], marker="o", linestyle="", markersize=11, color=t[a], label=lab)
               for a, lab in (("raw", "raw prompt"), ("skills", "with SDRF skills"))]
    leg = ax.legend(handles=handles, loc="lower left", frameon=False, fontsize=12, ncol=2,
                    bbox_to_anchor=(0, 1.04), labelcolor=t["ink"])
    leg.set_in_layout(False)

    # Cost column: text, in ink tokens (never the series colour).
    ax_cost.axis("off")
    ax_cost.set_ylim(ax.get_ylim())
    ax_cost.set_title("cost per SDRF\n(API-equiv. $ · local min)", loc="left", color=t["ink"], fontsize=12.5, pad=10)
    for y, (base, arms) in zip(ys, groups):
        lines = [_cost_line(arms.get("skills")), _cost_line(arms.get("raw"))]
        ax_cost.text(0, y, "\n".join(x for x in lines if x), va="center", ha="left", fontsize=11.5,
                     color=t["ink2"], family="monospace", linespacing=1.6)

    # Middle: best-arm score by quantification type, sequential single-hue table.
    cmap = LinearSegmentedColormap.from_list("seq", t["ramp"])
    matrix = []
    for base, arms in groups:
        matrix.append([max((r["by_qtype"].get(q) or 0) for r in arms.values()) if any(
            r["by_qtype"].get(q) is not None for r in arms.values()) else math.nan for q in QTYPES])
    matrix += [[math.nan] * len(QTYPES) for _ in pending]
    ax_q.set_facecolor(t["surface"])
    ax_q.pcolormesh(range(len(QTYPES) + 1), [y - 0.5 for y in range(n_rows + 1)], matrix[::-1],
                    cmap=cmap, vmin=0, vmax=100, edgecolors=t["surface"], linewidth=2)
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            if not math.isnan(v):
                ink = _best_ink(cmap(v / 100)[:3])
                ax_q.text(j + 0.5, n_rows - 1 - i, f"{v:.0f}", ha="center", va="center", fontsize=13, color=ink)
    ax_q.set_ylim(ax.get_ylim())
    ax_q.set_xticks([j + 0.5 for j in range(len(QTYPES))], QTYPES, fontsize=12, color=t["ink2"])
    ax_q.set_yticks([])
    ax_q.tick_params(length=0)
    for s in ax_q.spines.values():
        s.set_visible(False)
    ax_q.set_title("best arm, by quant type", loc="left", color=t["ink"], fontsize=14, pad=10)

    # Right: manuscript effect (with minus without), per arm.
    _style(ax_ms, t)
    deltas = [r["ms_delta"] for r in summary if r["ms_delta"] is not None]
    lim = max([10.0] + [abs(d) * 1.25 for d in deltas])
    ax_ms.axvline(0, color=t["ink2"], linewidth=1)
    for y, (base, arms) in zip(ys, groups):
        for arm, dy in (("raw", -0.12), ("skills", 0.12)):
            row = arms.get(arm)
            if row and row["ms_delta"] is not None:
                ax_ms.scatter([row["ms_delta"]], [y + dy], s=110, color=t[arm], edgecolors=t["surface"],
                              linewidths=2, zorder=3)
    ax_ms.set_xlim(-lim, lim)
    ax_ms.set_ylim(ax.get_ylim())
    ax_ms.set_yticks([])
    ax_ms.set_xlabel("points gained from the manuscript", color=t["ink2"], fontsize=12)
    ax_ms.set_title("manuscript effect", loc="left", color=t["ink"], fontsize=14, pad=10)

    n_ds = max((r["n"] for r in summary), default=0)
    present = [q for q in QTYPES if any(r["by_qtype"].get(q) is not None for r in summary)]
    uplifts = [(arms["skills"]["headline"] - arms["raw"]["headline"], base)
               for base, arms in groups if "raw" in arms and "skills" in arms]
    subtitle = (f"n = {n_ds} dataset{'s' if n_ds != 1 else ''} ({', '.join(present)})"
                " × with/without manuscript")
    if uplifts:
        gain, base = max(uplifts)
        subtitle = f"The SDRF skills add up to {gain:+.0f} points ({display_name(base)})  ·  " + subtitle
    fig.text(0.02, 0.945, "SDRF annotation quality by model", fontsize=28, color=t["ink"], weight="bold")
    fig.text(0.02, 0.895, subtitle, fontsize=15, color=t["ink2"])
    fig.text(0.02, 0.025, "Score: 80% deterministic match to the curated SDRF (validity, completeness, "
             "ontology-aware cell accuracy, specificity) + 20% reference-guided LLM judge.\n"
             "Scores measure agreement with the curated SDRFs.  Whiskers: ±1 SEM across datasets.  "
             "⚠ n = runs that failed or exceeded the model's context window.",
             fontsize=10.5, color=t["ink2"], linespacing=1.5)
    path = Path(path)
    for ext, kw in (("svg", {}), ("png", {"dpi": 200})):
        fig.savefig(path.with_suffix(f".{ext}"), facecolor=t["surface"], **kw)
    plt.close(fig)


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


def render_backups(records: list[dict], summary: list[dict], outdir: Path, theme: str = "light") -> None:
    t = THEMES[theme]
    outdir = Path(outdir)
    write_summary_tsv(summary, outdir / "summary.tsv")
    labels = [r["model_id"] for r in summary][::-1]
    rows = summary[::-1]

    # Weighted score components, stacked (2px surface gaps between segments).
    fig, ax = plt.subplots(figsize=(13, 0.55 * len(rows) + 2), facecolor=t["surface"])
    _style(ax, t)
    left = [0.0] * len(rows)
    for (comp, weight), color in zip(COMPONENTS, t["slots"]):
        vals = [(r["components"][comp] or 0) * weight for r in rows]
        ax.barh(labels, vals, left=left, color=color, edgecolor=t["surface"], linewidth=2,
                label=f"{comp} (max {weight})", height=0.6)
        left = [a + b for a, b in zip(left, vals)]
    ax.set_xlim(0, 100)
    ax.set_xlabel("deterministic score points", color=t["ink2"])
    ax.legend(frameon=False, ncol=4, loc="lower left", bbox_to_anchor=(0, 1.0), labelcolor=t["ink"])
    fig.tight_layout()
    fig.savefig(outdir / "backup_components.png", dpi=160, facecolor=t["surface"])
    plt.close(fig)

    # Rich vs poor PRIDE metadata.
    fig, ax = plt.subplots(figsize=(13, 0.55 * len(rows) + 2), facecolor=t["surface"])
    _style(ax, t)
    ypos = range(len(rows))
    for k, (tier, color) in enumerate(zip(TIERS, t["slots"][2:])):
        ax.barh([y + (0.2 if k == 0 else -0.2) for y in ypos], [r["by_tier"][tier] or 0 for r in rows],
                height=0.38, color=color, edgecolor=t["surface"], linewidth=2, label=f"{tier} PRIDE metadata")
    ax.set_yticks(list(ypos), labels, color=t["ink"])
    ax.set_xlim(0, 100)
    ax.legend(frameon=False, ncol=2, loc="lower left", bbox_to_anchor=(0, 1.0), labelcolor=t["ink"])
    fig.tight_layout()
    fig.savefig(outdir / "backup_tier.png", dpi=160, facecolor=t["surface"])
    plt.close(fig)

    # Judge vs deterministic agreement (only when the judge ran).
    pairs = [(r["deterministic"], r["judge"]) for r in records if r.get("judge") is not None]
    if len(pairs) >= 3:
        fig, ax = plt.subplots(figsize=(7, 7), facecolor=t["surface"])
        _style(ax, t, grid_axis="both")
        ax.scatter(*zip(*pairs), s=60, color=t["raw"], edgecolors=t["surface"], linewidths=1.5, alpha=0.8)
        ax.plot([0, 100], [0, 100], color=t["ink2"], linewidth=1, linestyle="--")
        r = statistics.correlation(*zip(*pairs)) if len({p[0] for p in pairs}) > 1 else float("nan")
        ax.set_title(f"judge vs deterministic (Pearson r = {r:.2f}, n = {len(pairs)})", color=t["ink"], loc="left")
        ax.set_xlabel("deterministic", color=t["ink2"])
        ax.set_ylabel("judge", color=t["ink2"])
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        fig.tight_layout()
        fig.savefig(outdir / "backup_judge_agreement.png", dpi=160, facecolor=t["surface"])
        plt.close(fig)
