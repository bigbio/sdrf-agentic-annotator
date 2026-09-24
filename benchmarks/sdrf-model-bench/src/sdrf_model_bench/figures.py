"""Conference figure set: the story of the benchmark in eight slides, one style.

Every figure is drawn from scored runs (runs.jsonl) so it can be regenerated after a new run:

  sdrf-bench figures --main results/main/runs.jsonl --collab results/collaborators/ours.jsonl \
      --external results/collaborators/external.jsonl --history results/history/skills_v2.jsonl \
      --out results/figures

Encoding, fixed across the set: sdrf-skills = vermilion, prompt only = slate, collaborators'
own sessions = amber, human curator = ink. Scores are the deterministic score (0-100).
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Patch  # noqa: E402

INK, INK2, GRID, SURFACE = "#1b1f24", "#5b6470", "#e3e6ea", "#ffffff"
SKILLS, PROMPT, COLLAB, HUMAN = "#e4572e", "#8a99ab", "#f2a541", "#1b1f24"
RAMP = ["#dbe4ee", "#9fb6cd", "#5d7fa3", "#2f4f75"]
MODELS = [("opus-5", "Opus 5"), ("sonnet-5", "Sonnet 5"), ("haiku-4.5", "Haiku 4.5")]
# the experimental design of every dataset in the two packs
DESIGN = {
    "PXD000878": "LFQ", "PXD002804": "LFQ", "PXD003039": "LFQ", "PXD006008": "LFQ", "PXD015240": "LFQ",
    "PXD022949": "LFQ", "PXD005354": "LFQ", "PXD015744": "LFQ",
    "PXD016662": "DIA", "PXD041421": "DIA", "PXD058044": "DIA", "PXD060259": "DIA", "PXD065279": "DIA",
    "PXD014871": "TMT", "PXD026581": "TMT", "PXD036580": "TMT", "PXD062322": "TMT", "PXD037221": "TMT",
    "PXD013923": "SILAC", "PXD019515": "Single-cell", "PXD058436": "Immuno-\npeptidomics",
}
DESIGN_ORDER = ["LFQ", "DIA", "TMT", "SILAC", "Single-cell", "Immuno-\npeptidomics"]


def _style():
    plt.rcParams.update({
        "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 13, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
        "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "none",
    })


def _load(path) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _by_dataset(recs, key="deterministic"):
    """Mean per dataset first (replicates, conditions), then across datasets."""
    per = defaultdict(list)
    for r in recs:
        if r.get(key) is not None:
            per[r["accession"]].append(r[key])
    return _mean([statistics.fmean(v) for v in per.values()])


def _pick(recs, model=None, arm=None, accs=None):
    out = []
    for r in recs:
        mid = r["model_id"]
        if model and not mid.startswith(model + "-"):
            continue
        if arm and not mid.endswith("-" + arm):
            continue
        if accs is not None and r["accession"] not in accs:
            continue
        out.append(r)
    return out


def _fig(title, subtitle, footer=None):
    fig = plt.figure(figsize=(13.33, 7.5), facecolor=SURFACE)
    fig.text(0.045, 0.925, title, fontsize=27, weight="bold", color=INK)
    if subtitle:
        fig.text(0.045, 0.872, subtitle, fontsize=15, color=INK2)
    if footer:
        fig.text(0.045, 0.035, footer, fontsize=10.5, color=INK2, linespacing=1.5)
    return fig


def _ax(fig, rect, grid="x"):
    ax = fig.add_axes(rect)
    ax.set_facecolor(SURFACE)
    ax.spines["left"].set_visible(False)
    ax.tick_params(length=0, labelsize=13)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=1)
        ax.set_axisbelow(True)
    return ax


def _save(fig, out: Path, name: str):
    fig.savefig(out / f"{name}.png", dpi=300, facecolor=SURFACE)
    fig.savefig(out / f"{name}.svg", facecolor=SURFACE)
    plt.close(fig)


def _dumbbell(ax, rows, lo=50, hi=95, ref=None, ref_label=None):
    """rows: [(label, prompt, skills)] top to bottom."""
    ys = list(range(len(rows)))[::-1]
    for y, (label, p, s) in zip(ys, rows):
        ax.plot([p, s], [y, y], color=GRID, linewidth=6, solid_capstyle="round", zorder=1)
        ax.scatter([p], [y], s=260, color=PROMPT, zorder=3, edgecolors=SURFACE, linewidths=2)
        ax.scatter([s], [y], s=320, color=SKILLS, zorder=4, edgecolors=SURFACE, linewidths=2)
        ax.text(min(p, s) - 1.2, y, f"{min(p, s):.0f}", ha="right", va="center", fontsize=13,
                color=PROMPT if p <= s else SKILLS)
        ax.text(max(p, s) + 1.2, y, f"{max(p, s):.0f}", ha="left", va="center", fontsize=13,
                color=SKILLS if s >= p else PROMPT, weight="bold")
        d = s - p
        ax.text(1.03, y, f"{d:+.0f}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=18,
                weight="bold", color=SKILLS if d > 0 else INK2)
    if ref is not None:
        ax.axvline(ref, color=COLLAB, linewidth=2.5, linestyle=(0, (4, 3)), zorder=2)
        ax.text(ref, len(rows) - 0.45, ref_label, ha="center", va="bottom", fontsize=11.5, color="#b8741a")
    ax.set_yticks(ys, [r[0] for r in rows], fontsize=16)
    ax.set_xlim(lo, hi)
    ax.set_ylim(-0.6, len(rows) - 0.2)
    ax.set_xlabel("score (0-100): agreement with the curated SDRF", fontsize=12)


def _arm_legend(fig, extra=(), y=0.80):
    handles = [Line2D([], [], marker="o", linestyle="", color=PROMPT, markersize=13),
               Line2D([], [], marker="o", linestyle="", color=SKILLS, markersize=13)]
    labels = ["prompt only", "with sdrf-skills"]
    for h, lab in extra:
        handles.append(h)
        labels.append(lab)
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(0.04, y), ncol=len(labels), frameon=False,
               fontsize=13, labelcolor=INK, handletextpad=0.4, columnspacing=1.8)


# ----------------------------------------------------------------------------- 1. impact

def fig_impact(main, collab, external, out):
    dai = sorted({r["accession"] for r in external if r["model_id"].startswith("dai-")})
    fig = _fig("sdrf-skills lifts every model, most of all the smallest",
               "Mean score per model, prompt only vs the same model with sdrf-skills (offline, no paper)",
               "Left: 15 PRIDE datasets (6 LFQ, 5 DIA, 4 TMT). Right: the 4 datasets of Chengxin Dai's manual-vs-skills "
               "benchmark; dashed = Dai's own skills session,\nwhich had network access and the paper. "
               "Deterministic score: validity 20, completeness 15, accuracy 50, specificity 15. One run per dataset.")
    for i, (recs, accs, name) in enumerate(((main, None, "15 benchmark datasets"),
                                            (collab, set(dai), "Chengxin Dai's 4 datasets"))):
        ax = _ax(fig, [0.13 + i * 0.45, 0.17, 0.34, 0.56])
        rows = [(label, _by_dataset(_pick(recs, m, "raw", accs)), _by_dataset(_pick(recs, m, "skills", accs)))
                for m, label in MODELS]
        ref = _by_dataset([r for r in external if r["model_id"] == "dai-skills"]) if i else None
        _dumbbell(ax, rows, lo=55, hi=92, ref=ref, ref_label=f"Dai's session: {ref:.0f}" if ref else None)
        ax.set_title(name, fontsize=16, color=INK, loc="left", pad=12, weight="bold")
        if i:
            ax.set_yticklabels([])
    _arm_legend(fig)
    _save(fig, out, "fig1_skills_impact")


# ----------------------------------------------------------------------------- 2. cost vs quality

def fig_cost_quality(main, out):
    fig = _fig("Skills buy quality: free for Haiku, a premium for Opus and Sonnet",
               "Cost per SDRF (API-equivalent, log scale) against score; arrows go from prompt only to sdrf-skills",
               "15 benchmark datasets, offline, no paper. Cost as reported by Claude Code (total_cost_usd), mean per SDRF.")
    ax = _ax(fig, [0.09, 0.15, 0.84, 0.62], grid="both")
    for m, label in MODELS:
        p, s = _pick(main, m, "raw"), _pick(main, m, "skills")
        cp, cs = _mean(r["cost_usd"] for r in p), _mean(r["cost_usd"] for r in s)
        qp, qs = _by_dataset(p), _by_dataset(s)
        ax.annotate("", xy=(cs, qs), xytext=(cp, qp),
                    arrowprops={"arrowstyle": "-|>", "color": INK2, "lw": 1.8, "mutation_scale": 18, "shrinkA": 14, "shrinkB": 16})
        ax.scatter([cp], [qp], s=420, color=PROMPT, zorder=3, edgecolors=SURFACE, linewidths=2)
        ax.scatter([cs], [qs], s=520, color=SKILLS, zorder=4, edgecolors=SURFACE, linewidths=2)
        sk_off, pr_off = {"opus-5": ((16, 14), (0, 24)), "sonnet-5": ((10, -30), (0, -28)),
                          "haiku-4.5": ((16, 4), (0, -28))}[m]
        ax.annotate(f"{label}\n${cs:.2f} · {qs:.0f}", (cs, qs), xytext=sk_off, textcoords="offset points",
                    fontsize=14, color=INK, weight="bold", va="center")
        ax.annotate(f"${cp:.2f} · {qp:.0f}", (cp, qp), xytext=pr_off, textcoords="offset points",
                    fontsize=11.5, color=INK2, ha="center", va="center")
    ax.set_xscale("log")
    ticks = [0.2, 0.5, 1, 2, 5]
    ax.set_xticks(ticks, [f"${t:g}" for t in ticks])
    ax.minorticks_off()
    ax.set_xlim(0.18, 7)
    ax.set_ylim(62, 86)
    ax.set_xlabel("cost per SDRF (US$, log scale)", fontsize=13)
    ax.set_ylabel("score (0-100)", fontsize=13)
    ax.tick_params(axis="y", colors=INK2)
    _arm_legend(fig)
    _save(fig, out, "fig2_cost_vs_quality")


# ----------------------------------------------------------------------------- 3. time and cost vs human

def fig_human(collab, external, out):
    dai = [r for r in external if r["model_id"] == "dai-skills"]
    accs = {r["accession"] for r in dai}
    human = _mean(r["human_min"] for r in dai)
    rows = [("Human curator", human, None, HUMAN), ("Dai, sdrf-skills session", _mean(r["wall_s"] for r in dai) / 60,
                                                    None, COLLAB)]
    for m, label in MODELS:
        for arm, col, name in (("skills", SKILLS, "+ sdrf-skills"), ("raw", PROMPT, "prompt only")):
            recs = _pick(collab, m, arm, accs)
            rows.append((f"{label} {name}", _mean(r["wall_s"] for r in recs) / 60,
                         _mean(r["cost_usd"] for r in recs), col))
    fig = _fig("From 36 minutes of curation to a few minutes and a few dollars",
               "Minutes per SDRF on Chengxin Dai's 4 datasets (12 to 1,560 rows), with the API cost of each AI run",
               "Human and Dai's session times from Dai's manual-vs-skills benchmark (same 4 datasets). "
               "Our runs: offline, no paper, 3 in parallel on one laptop; cost = Claude Code total_cost_usd.")
    ax = _ax(fig, [0.30, 0.13, 0.56, 0.68])
    ys = list(range(len(rows)))[::-1]
    for y, (label, mins, cost, col) in zip(ys, rows):
        ax.barh(y, mins, height=0.64, color=col, edgecolor=SURFACE, linewidth=2)
        speed = f"   {human / mins:.0f}× faster" if col not in (HUMAN,) and mins < human else ""
        txt = f"{mins:.0f} min" + (f" · ${cost:.2f}" if cost is not None else "") + speed
        ax.text(mins + 0.6, y, txt, va="center", fontsize=13, color=INK, weight="bold" if col == HUMAN else None)
    ax.set_yticks(ys, [r[0] for r in rows], fontsize=14)
    ax.set_xlim(0, 52)
    ax.set_xlabel("minutes per SDRF (mean over the 4 datasets)", fontsize=12)
    _save(fig, out, "fig3_time_and_cost_vs_human")


# ----------------------------------------------------------------------------- 4. quality breakdown

COMPONENTS = (("validity", 20, "valid file"), ("completeness", 15, "columns & rows present"),
              ("accuracy", 50, "correct values"), ("specificity", 15, "no needless 'not available'"))
TRIAGE = (("match", "#3b7d4f", "correct"), ("style", "#9ccaa4", "style only"),
          ("run_wrong", SKILLS, "wrong"), ("curated_richer", "#f6c1a8", "blank where the reference has a value"))


def fig_quality(main, out):
    configs = [(m, arm, f"{label} {'+ skills' if arm == 'skills' else 'prompt only'}")
               for m, label in MODELS for arm in ("skills", "raw")]
    fig = _fig("Where the points are won and lost",
               "Left: the score split into its four parts. Right: every scored cell, classified against the curated SDRF",
               "15 benchmark datasets, offline, no paper. Cell classes decided by rule (after bigbio/sdrf-skills PR #24); "
               "reference faults are not charged to the run.")
    ys = list(range(len(configs)))[::-1]
    ax = _ax(fig, [0.21, 0.15, 0.36, 0.6])
    for y, (m, arm, label) in zip(ys, configs):
        recs = _pick(main, m, arm)
        left = 0.0
        for (comp, w, _), col in zip(COMPONENTS, RAMP):
            v = (_mean(r.get(comp) for r in recs) or 0) * w
            ax.barh(y, v, left=left, height=0.62, color=col, edgecolor=SURFACE, linewidth=1.5)
            if v >= 7:
                ax.text(left + v / 2, y, f"{v:.0f}", ha="center", va="center", fontsize=11,
                        color=INK if col in RAMP[:2] else SURFACE)
            left += v
        ax.text(left + 1.5, y, f"{left:.0f}", va="center", fontsize=13, weight="bold", color=INK)
    ax.set_yticks(ys, [c[2] for c in configs], fontsize=13.5)
    ax.set_xlim(0, 100)
    ax.set_xlabel("points", fontsize=12)
    ax.legend([Patch(color=c) for c in RAMP], [f"{n} ({w})" for _, w, n in COMPONENTS], loc="lower left",
              bbox_to_anchor=(-0.02, 1.01), ncol=2, frameon=False, fontsize=11, labelcolor=INK)
    ax2 = _ax(fig, [0.61, 0.15, 0.33, 0.6])
    for y, (m, arm, _) in zip(ys, configs):
        tot = defaultdict(int)
        for r in _pick(main, m, arm):
            for k, v in (r.get("triage") or {}).items():
                tot[k] += v
        n = sum(tot[k] for k, _, _ in TRIAGE) or 1
        left = 0.0
        for k, col, _ in TRIAGE:
            w = 100 * tot[k] / n
            ax2.barh(y, w, left=left, height=0.62, color=col, edgecolor=SURFACE, linewidth=1.5)
            if w >= 8:
                ax2.text(left + w / 2, y, f"{w:.0f}%", ha="center", va="center", fontsize=11,
                         color=SURFACE if col in ("#3b7d4f", SKILLS) else INK)
            left += w
    ax2.set_yticks(ys, [""] * len(ys))
    ax2.set_xlim(0, 100)
    ax2.set_xlabel("share of scored cells (%)", fontsize=12)
    ax2.legend([Patch(color=c) for _, c, _ in TRIAGE], [n for _, _, n in TRIAGE], loc="lower left",
               bbox_to_anchor=(-0.02, 1.01), ncol=2, frameon=False, fontsize=11, labelcolor=INK)
    _save(fig, out, "fig4_quality_breakdown")


# ----------------------------------------------------------------------------- 5. skills v2 -> v4

def fig_evolution(main, history, out):
    metrics = (("score", lambda rs: _by_dataset(rs), "{:.0f}", (50, 90)),
               ("cost per SDRF", lambda rs: _mean(r["cost_usd"] for r in rs), "${:.2f}", (0, 5.5)),
               ("minutes per SDRF", lambda rs: _mean(r["wall_s"] for r in rs) / 60, "{:.0f}", (0, 15)),
               ("files that validate", lambda rs: 100 * _mean(r.get("validity") for r in rs), "{:.0f}%", (70, 102)))
    fig = _fig("The redesign: cheaper, faster, and Haiku no longer breaks",
               "Same benchmark, same models: sdrf-skills before (v2) and after the redesign (contract + build, "
               "reference files loaded on demand)",
               "15 benchmark datasets, offline, no paper. v2 = sdrf-skills as shipped before bigbio/sdrf-skills "
               "#91-#98; after = merged #91-#98.")
    cols = {"opus-5": "#2f4f75", "sonnet-5": "#7d9cbd", "haiku-4.5": SKILLS}
    fig.legend([Line2D([], [], color=cols[m], linewidth=4) for m, _ in MODELS], [lab for _, lab in MODELS],
               loc="lower left", bbox_to_anchor=(0.04, 0.80), ncol=3, frameon=False, fontsize=14, labelcolor=INK)
    for i, (name, fn, fmt, lim) in enumerate(metrics):
        ax = _ax(fig, [0.06 + i * 0.235, 0.16, 0.17, 0.58], grid="y")
        ax.spines["left"].set_visible(True)
        vals = {m: (fn(_pick(history, m, "skills")), fn(_pick(main, m, "skills"))) for m, _ in MODELS}
        gap = (lim[1] - lim[0]) * 0.055
        for side in (0, 1):
            placed = _spread({m: v[side] for m, v in vals.items()}, gap)
            for m, _ in MODELS:
                ax.text(-0.08 if side == 0 else 1.08, placed[m], fmt.format(vals[m][side]),
                        ha="right" if side == 0 else "left", va="center", fontsize=12, color=cols[m],
                        weight="bold" if side else None)
        for m, _ in MODELS:
            ax.plot([0, 1], vals[m], color=cols[m], linewidth=3.2, marker="o", markersize=11,
                    markeredgecolor=SURFACE)
        ax.set_xticks([0, 1], ["before", "after"], fontsize=13)
        ax.tick_params(axis="x", colors=INK)
        ax.set_xlim(-0.55, 1.55)
        ax.set_ylim(*lim)
        ax.set_yticks([])
        ax.set_title(name, fontsize=15, color=INK, weight="bold", loc="center", pad=10)
    _save(fig, out, "fig5_skills_before_after")


# ----------------------------------------------------------------------------- 6. where to optimise next

FIELD_FIX = {
    "comment[modification parameters]": "search settings", "comment[fragment mass tolerance]": "search settings",
    "comment[precursor mass tolerance]": "search settings", "comment[cleavage agent details]": "search settings",
    "characteristics[cell type]": "sample metadata", "characteristics[disease]": "sample metadata",
    "characteristics[organism part]": "sample metadata", "comment[fraction identifier]": "design & files",
    "comment[label]": "design & files", "comment[technical replicate]": "design & files",
    "comment[instrument]": "instrument", "characteristics[organism]": "sample metadata",
}
FIX_COL = {"search settings": SKILLS, "sample metadata": "#2f4f75", "design & files": "#8a99ab", "instrument": "#c7cfd8"}
FIX_IDEA = {
    "search settings": "read them from the deposited search files: sdrf-tools search-params (MaxQuant, FragPipe, "
                       "DIA-NN, PD) - sdrf-skills #99",
    "sample metadata": "ground them in the paper and cell-line records (Cellosaurus) before inventing a value",
    "design & files": "derive fractions, replicates and channels from file names and the search design",
}


def fig_next(main, collab, out):
    per = defaultdict(list)
    for r in main + collab:
        if r["model_id"].endswith("-skills"):
            for k, v in (r.get("field_accuracy") or {}).items():
                per[k].append(v)
    fields = sorted((k for k in per if k in FIELD_FIX and k != "characteristics[organism]"),
                    key=lambda k: statistics.fmean(per[k]))
    fig = _fig("Where sdrf-skills still loses points, and what fixes it",
               "Accuracy per field for the skills runs (all models, both packs), coloured by the kind of fix it needs",
               "Share of rows where the field matches the curated SDRF (style differences not penalised). "
               "All sdrf-skills runs, offline, no paper.")
    ax = _ax(fig, [0.31, 0.2, 0.32, 0.56])
    ys = list(range(len(fields)))[::-1]
    for y, k in zip(ys, fields):
        v = 100 * statistics.fmean(per[k])
        ax.barh(y, v, height=0.64, color=FIX_COL[FIELD_FIX[k]], edgecolor=SURFACE, linewidth=1.5)
        ax.text(v + 1.5, y, f"{v:.0f}%", va="center", fontsize=12.5, color=INK, weight="bold")
    ax.set_yticks(ys, [k.replace("characteristics[", "").replace("comment[", "").rstrip("]") for k in fields],
                  fontsize=13.5)
    ax.set_xlim(0, 110)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("rows matching the curated SDRF (%)", fontsize=12)
    y0 = 0.74
    for fix in ("search settings", "sample metadata", "design & files"):
        fig.patches.append(FancyBboxPatch((0.665, y0 - 0.145), 0.30, 0.15, boxstyle="round,pad=0.008,rounding_size=0.012",
                                          transform=fig.transFigure, facecolor="#f6f7f9", edgecolor=FIX_COL[fix],
                                          linewidth=2.2))
        fig.text(0.68, y0 - 0.02, fix, fontsize=15, weight="bold", color=FIX_COL[fix] if fix != "design & files" else INK2)
        fig.text(0.68, y0 - 0.045, _wrap(FIX_IDEA[fix], 44), fontsize=11.5, color=INK, va="top", linespacing=1.35)
        y0 -= 0.19
    _save(fig, out, "fig6_where_to_optimise")


def _spread(vals: dict, gap: float) -> dict:
    """Label positions at least `gap` apart, as close to their values as possible."""
    pos = {}
    for m in sorted(vals, key=vals.get, reverse=True):  # from the top down, so labels never leave the panel
        pos[m] = vals[m] if not pos else min(vals[m], min(pos.values()) - gap)
    return pos


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return "\n".join(lines + [cur])


# ----------------------------------------------------------------------------- 7. design difficulty

def fig_designs(main, collab, out):
    recs = main + collab
    configs = [(m, arm, f"{label} {'+ skills' if arm == 'skills' else 'prompt only'}")
               for m, label in MODELS for arm in ("skills", "raw")]
    designs = [d for d in DESIGN_ORDER if any(DESIGN.get(r["accession"]) == d for r in recs)]
    fig = _fig("Some experimental designs are much harder to annotate",
               "Mean score by experimental design (left) and what an SDRF costs to produce (right)",
               "Both packs (21 datasets), offline, no paper; n = datasets per design; n/a = run missing. TMT includes PXD037221, whose record "
               "holds no protocol text: without the paper no run\nrecognises the TMT design (all score 20). "
               "SILAC, single-cell and immunopeptidomics are one dataset each.")
    ax = _ax(fig, [0.18, 0.17, 0.46, 0.56], grid=None)
    grid = [[_by_dataset([r for r in _pick(recs, m, arm) if DESIGN.get(r["accession"]) == d]) for d in designs]
            for m, arm, _ in configs]
    cmap = matplotlib.colormaps["RdYlGn"]
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            if v is None:
                ax.add_patch(plt.Rectangle((j, len(grid) - 1 - i), 0.94, 0.9, color="#eef0f3"))
                ax.text(j + 0.47, len(grid) - 1 - i + 0.45, "n/a", ha="center", va="center", fontsize=12,
                        color=INK2)
                continue
            ax.add_patch(plt.Rectangle((j, len(grid) - 1 - i), 0.94, 0.9, color=cmap((v - 20) / 75)))
            ax.text(j + 0.47, len(grid) - 1 - i + 0.45, f"{v:.0f}", ha="center", va="center", fontsize=14,
                    weight="bold", color=INK)
    n = {d: len({r["accession"] for r in recs if DESIGN.get(r["accession"]) == d}) for d in designs}
    ax.set_xlim(0, len(designs))
    ax.set_ylim(0, len(grid))
    ax.set_xticks([j + 0.47 for j in range(len(designs))], [f"{d}\nn={n[d]}" for d in designs], fontsize=12)
    ax.xaxis.tick_top()
    ax.set_yticks([len(grid) - 1 - i + 0.45 for i in range(len(grid))], [c[2] for c in configs], fontsize=13)
    ax.spines["bottom"].set_visible(False)
    ax2 = _ax(fig, [0.785, 0.19, 0.17, 0.54])
    ys = list(range(len(designs)))[::-1]
    for y, d in zip(ys, designs):
        for off, arm, col in ((0.18, "raw", PROMPT), (-0.18, "skills", SKILLS)):
            c = _mean(r["cost_usd"] for r in recs if DESIGN.get(r["accession"]) == d and r["model_id"].endswith(arm))
            ax2.barh(y + off, c, height=0.34, color=col, edgecolor=SURFACE)
            ax2.text(c + 0.1, y + off, f"${c:.2f}", va="center", fontsize=11, color=INK)
    ax2.set_yticks(ys, designs, fontsize=12)
    ax2.set_xlabel("mean cost per SDRF (US$)", fontsize=12)
    ax2.set_title("cost per SDRF", fontsize=14, color=INK, weight="bold", loc="left", pad=28)
    ax2.legend([Patch(color=PROMPT), Patch(color=SKILLS)], ["prompt only", "sdrf-skills"], loc="lower left",
               bbox_to_anchor=(-0.05, 1.0), ncol=2, frameon=False, fontsize=11, labelcolor=INK, handlelength=1)
    _save(fig, out, "fig7_design_difficulty")


# ----------------------------------------------------------------------------- 8. cost vs size

def fig_size(main, collab, out, data_dirs):
    rows = {}
    for d in data_dirs:
        with open(Path(d) / "manifest.tsv", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                rows[r["accession"]] = int(r["n_rows"])
    fig = _fig("sdrf-skills cost stays flat as the SDRF grows",
               "Cost per SDRF against its size: prompt-only models write every row; sdrf-skills writes two small "
               "tables and build expands them",
               "Every run of both packs, offline, no paper. Size = rows of the curated SDRF. Lines: least-squares fit on "
               "log-log axes, per arm.")
    ax = _ax(fig, [0.09, 0.14, 0.84, 0.64], grid="both")
    for arm, col in (("raw", PROMPT), ("skills", SKILLS)):
        pts = [(rows[r["accession"]], r["cost_usd"]) for r in main + collab
               if r["model_id"].endswith(arm) and r.get("cost_usd") and r["accession"] in rows]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        ax.scatter(xs, ys, s=70, color=col, alpha=0.75, edgecolors=SURFACE, linewidths=0.8, zorder=3)
        lx, ly = [math.log10(x) for x in xs], [math.log10(y) for y in ys]
        mx, my = statistics.fmean(lx), statistics.fmean(ly)
        b = sum((a - mx) * (c - my) for a, c in zip(lx, ly)) / sum((a - mx) ** 2 for a in lx)
        a0 = my - b * mx
        grid = [10, 30, 100, 300, 1000, 1600]
        ax.plot(grid, [10 ** (a0 + b * math.log10(g)) for g in grid], color=col, linewidth=3, zorder=4)
        ax.text(1700, 10 ** (a0 + b * math.log10(1600)), f"{'prompt only' if arm == 'raw' else 'sdrf-skills'}\n"
                f"×{10 ** (b * 2):.1f} per 100× rows", va="center", fontsize=12.5, color=col, weight="bold")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks([10, 30, 100, 300, 1000], ["10", "30", "100", "300", "1,000"])
    ax.set_yticks([0.1, 0.3, 1, 3, 10], ["$0.10", "$0.30", "$1", "$3", "$10"])
    ax.minorticks_off()
    ax.set_xlim(8, 4000)
    ax.set_xlabel("rows in the SDRF (log scale)", fontsize=13)
    ax.set_ylabel("cost per SDRF (US$, log scale)", fontsize=13)
    ax.tick_params(axis="y", colors=INK2)
    _save(fig, out, "fig8_cost_vs_size")


def render_all(main_path, collab_path, external_path, history_path, out, data_dirs=("data", "data-ext")):
    _style()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    offp = lambda rs: [r for r in rs if not r.get("manuscript")]  # noqa: E731
    main, collab = offp(_load(main_path)), offp(_load(collab_path))
    external, history = _load(external_path), offp(_load(history_path))
    fig_impact(main, collab, external, out)
    fig_cost_quality(main, out)
    fig_human(collab, external, out)
    fig_quality(main, out)
    if history:
        fig_evolution(main, history, out)
    fig_next(main, collab, out)
    fig_designs(main, collab, out)
    fig_size(main, collab, out, data_dirs)
    return sorted(p.name for p in out.glob("*.png"))
