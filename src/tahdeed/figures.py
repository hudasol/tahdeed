"""Figures for the docs, drawn from the evaluation / studies JSON (matplotlib, SVG output)."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, MUTE, BLUE, AMBER, RED = "#10303a", "#7b8f95", "#2b3fc4", "#b87a06", "#a63a3a"


def _style(ax, title: str, xl: str, yl: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=10)
    ax.set_xlabel(xl, color=INK)
    ax.set_ylabel(yl, color=INK)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTE)
    ax.tick_params(colors=INK)
    ax.grid(axis="y", color="#dde5e7", lw=0.7)
    ax.set_axisbelow(True)


def reliability(ev: dict, out: Path) -> None:
    rows = ev["abu_dhabi_structured"]["reliability_p50"]
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    ax.plot([0, 1], [0, 1], color=MUTE, lw=1, ls="--", label="perfectly calibrated")
    ax.plot(
        [r["mean_p"] for r in rows],
        [r["frac_correct"] for r in rows],
        color=BLUE,
        marker="o",
        ms=4,
        lw=1.6,
        label="tahdeed",
    )
    for r in rows:
        if r["n"] >= 500:
            ax.annotate(
                f"n={r['n']}",
                (r["mean_p"], r["frac_correct"]),
                textcoords="offset points",
                xytext=(6, -12),
                fontsize=7,
                color=MUTE,
            )
    _style(
        ax,
        f"Stated vs. observed accuracy (ECE {ev['abu_dhabi_structured']['ece_p50']:.3f})",
        "stated P(within 50 m)",
        "fraction within 50 m",
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "reliability.svg")
    plt.close(fig)


def risk_coverage(ev: dict, out: Path) -> None:
    pts = ev["abu_dhabi_structured"]["risk_coverage"]
    fig, ax = plt.subplots(figsize=(4.8, 4.2))
    ax.plot(
        [p["coverage"] for p in pts],
        [p["precision_50m"] for p in pts],
        color=BLUE,
        marker="o",
        ms=4,
        lw=1.6,
    )
    _style(
        ax,
        "Answer only what you are sure of",
        "share of queries answered (most confident first)",
        "within 50 m",
    )
    ax.set_ylim(0.5, 1.01)
    ax.set_xlim(0, 1.02)
    fig.tight_layout()
    fig.savefig(out / "risk_coverage.svg")
    plt.close(fig)


def hole_sensitivity(ev: dict, out: Path) -> None:
    hs = ev["hole_sensitivity"]
    xs = [float(k) * 100 for k in hs]
    fig, ax = plt.subplots(figsize=(5.2, 4.2))
    ax.plot(
        xs,
        [v["resolved_precision_50m"] * 100 for v in hs.values()],
        color=BLUE,
        marker="o",
        lw=1.6,
        label="precision of confident answers",
    )
    ax.plot(
        xs,
        [v["resolved_coverage"] * 100 for v in hs.values()],
        color=AMBER,
        marker="s",
        lw=1.6,
        label="share answered confidently",
    )
    ax.axvline(30, color=MUTE, lw=0.8, ls=":")
    ax.annotate(
        "training mix", (30, 52), fontsize=7, color=MUTE, rotation=90, va="bottom", ha="right"
    )
    _style(
        ax,
        "When the true address is missing from the registry",
        "queries whose true address is absent (%)",
        "%",
    )
    ax.set_ylim(40, 100)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(out / "hole_sensitivity.svg")
    plt.close(fig)


def generator_gap(st: dict, out: Path) -> None:
    g = st["generator_gap"]
    labels = ["v1: English names\nperturbed", "v2: from Arabic\nnames"]
    keys = ["v1_english_perturbed", "v2_from_arabic"]
    fig, ax = plt.subplots(figsize=(5.0, 4.2))
    w = 0.34
    for i, (name, col) in enumerate((("forced_top1_50m", BLUE), ("resolved_precision_50m", AMBER))):
        vals = [g[k][name] * 100 for k in keys]
        ax.bar(
            [x + (i - 0.5) * w for x in range(2)],
            vals,
            w,
            color=col,
            label={
                "forced_top1_50m": "top-1 within 50 m (always answer)",
                "resolved_precision_50m": "precision of confident answers",
            }[name],
        )
        for x, v in zip(range(2), vals, strict=True):
            ax.text(x + (i - 0.5) * w, v + 1, f"{v:.0f}", ha="center", fontsize=8, color=INK)
    ax.set_xticks(range(2), labels)
    _style(ax, "Does it hold on queries we did not write?", "", "%")
    ax.set_ylim(0, 128)
    ax.legend(frameon=False, fontsize=7.5, loc="upper center", ncol=1)
    fig.tight_layout()
    fig.savefig(out / "generator_gap.svg")
    plt.close(fig)


def ablation(st: dict, out: Path) -> None:
    rows = st["ablations"]["rows"]
    names = [k for k in rows if k != "full system"]
    diffs = [rows[k]["top1_vs_full"]["diff"] * 100 for k in names]
    lo = [rows[k]["top1_vs_full"]["ci95"][0] * 100 for k in names]
    hi = [rows[k]["top1_vs_full"]["ci95"][1] * 100 for k in names]
    order = sorted(range(len(names)), key=lambda i: diffs[i])
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    y = range(len(order))
    ax.barh(
        list(y),
        [diffs[i] for i in order],
        color=[RED if diffs[i] < 0 else BLUE for i in order],
        height=0.55,
    )
    ax.errorbar(
        [diffs[i] for i in order],
        list(y),
        xerr=[[diffs[i] - lo[i] for i in order], [hi[i] - diffs[i] for i in order]],
        fmt="none",
        ecolor=INK,
        lw=1,
        capsize=2,
    )
    ax.set_yticks(list(y), [names[i] for i in order], fontsize=8)
    ax.axvline(0, color=INK, lw=0.8)
    _style(
        ax,
        "What each component is worth (top-1 within 50 m vs. full system)",
        "change in percentage points, 95% paired bootstrap",
        "",
    )
    ax.grid(axis="x", color="#dde5e7", lw=0.7)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out / "ablation.svg")
    plt.close(fig)


def make_all(eval_json: str, studies_json: str, out_dir: str) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ev = json.loads(Path(eval_json).read_text())
    made = []
    for fn in (reliability, risk_coverage, hole_sensitivity):
        fn(ev, out)
        made.append(fn.__name__)
    if Path(studies_json).exists():
        st = json.loads(Path(studies_json).read_text())
        for fn in (generator_gap, ablation):
            fn(st, out)
            made.append(fn.__name__)
    return made
