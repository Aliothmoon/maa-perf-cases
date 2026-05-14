#!/usr/bin/env python3
"""
plot_perf.py — render PR-ready performance charts from bench_matcher output.

Inputs (relative to repo root):
  RegressionCases/baseline/{windows,android}/{coverage,perf}.txt
  data/windows/{coverage,perf}_run{1,2}.txt   (min-of-2 used)
  data/android/{coverage,perf}.txt            (single run, Android is stable)

Outputs:
  docs/figures/percentiles.png
  docs/figures/cdf.png
  docs/figures/speedup_hist.png
  docs/figures/scatter.png

Usage:
  python scripts/plot_perf.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[1]
FIG_DIR = REPO / "docs" / "figures"

LINE = re.compile(
    r"^(\S+)\s+min=\s*(\d+)\s+p50=\s*(\d+)\s+p95=\s*(\d+)\s+avg=\s*(\d+)\s+max=\s*(\d+)"
)


def parse(path: Path) -> Dict[str, int]:
    """Return {sample_id: avg_us}. Skips header / footer lines."""
    if not path.exists():
        print(f"  [warn] missing: {path}", file=sys.stderr)
        return {}
    out: Dict[str, int] = {}
    for line in path.read_text(errors="replace").splitlines():
        m = LINE.match(line.strip())
        if m:
            out[m.group(1)] = int(m.group(5))
    return out


def merge_min(a: Dict[str, int], b: Dict[str, int]) -> Dict[str, int]:
    common = set(a) & set(b)
    return {s: min(a[s], b[s]) for s in common}


def load_all():
    base = {}
    post = {}
    for plat in ("windows", "android"):
        for ds in ("coverage", "perf"):
            base[(plat, ds)] = parse(REPO / "RegressionCases" / "baseline" / plat / f"{ds}.txt")
        if plat == "windows":
            for ds in ("coverage", "perf"):
                r1 = parse(REPO / "data"  / "windows" / f"{ds}_run1.txt")
                r2 = parse(REPO / "data"  / "windows" / f"{ds}_run2.txt")
                post[(plat, ds)] = merge_min(r1, r2) if r2 else r1
        else:
            for ds in ("coverage", "perf"):
                post[(plat, ds)] = parse(REPO / "data"  / "android" / f"{ds}.txt")
    return base, post


def percentile(arr, p):
    s = sorted(arr)
    if not s:
        return 0
    return s[min(int(len(s) * p / 100), len(s) - 1)]


# ---- 1. percentile bars -----------------------------------------------------

def fig_percentiles(base, post):
    pcts = ["p50", "p75", "p90", "p95", "p99", "mean"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for (plat, ds), ax in zip(
        [("windows", "coverage"), ("windows", "perf"),
         ("android", "coverage"), ("android", "perf")], axes.flat):
        b = list(base[(plat, ds)].values())
        p = [post[(plat, ds)][s] for s in base[(plat, ds)] if s in post[(plat, ds)]]
        if not b or not p:
            ax.set_visible(False); continue
        vals_b = [percentile(b, x) for x in (50, 75, 90, 95, 99)] + [int(np.mean(b))]
        vals_p = [percentile(p, x) for x in (50, 75, 90, 95, 99)] + [int(np.mean(p))]
        x = np.arange(len(pcts))
        w = 0.38
        ax.bar(x - w / 2, vals_b, w, label="baseline", color="#9aa0a6")
        ax.bar(x + w / 2, vals_p, w, label="optimized",    color="#1a73e8")
        for i, (bv, pv) in enumerate(zip(vals_b, vals_p)):
            ax.text(i + w / 2, pv, f"{pv/1000:.1f}ms" if pv >= 1000 else f"{pv}us",
                    ha="center", va="bottom", fontsize=7, color="#1a73e8")
        ax.set_xticks(x); ax.set_xticklabels(pcts)
        ax.set_yscale("log")
        ax.set_ylabel("time (us, log)")
        ax.set_title(f"{plat} / {ds} (n={len(b)})")
        ax.grid(axis="y", which="both", alpha=0.3)
        ax.legend(loc="upper left")
    fig.suptitle("Latency percentiles: baseline vs optimized", fontsize=14, y=1.00)
    fig.tight_layout()
    out = FIG_DIR / "percentiles.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---- 2. CDF -----------------------------------------------------------------

def fig_cdf(base, post):
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for (plat, ds), ax in zip(
        [("windows", "coverage"), ("windows", "perf"),
         ("android", "coverage"), ("android", "perf")], axes.flat):
        b = sorted(base[(plat, ds)].values())
        p = sorted(post[(plat, ds)][s] for s in base[(plat, ds)] if s in post[(plat, ds)])
        if not b or not p:
            ax.set_visible(False); continue
        yb = np.linspace(0, 1, len(b), endpoint=True)
        yp = np.linspace(0, 1, len(p), endpoint=True)
        ax.plot(b, yb, color="#9aa0a6", label="baseline", linewidth=2)
        ax.plot(p, yp, color="#1a73e8", label="optimized",    linewidth=2)
        ax.set_xscale("log")
        ax.set_xlabel("time (us, log)")
        ax.set_ylabel("CDF")
        ax.set_title(f"{plat} / {ds}  (n={len(b)})")
        ax.grid(which="both", alpha=0.3)
        ax.legend(loc="lower right")
        # mark p50/p95/p99 visually
        for q, ls in [(0.50, ":"), (0.95, "--"), (0.99, "-.")]:
            ax.axhline(q, color="black", linewidth=0.6, linestyle=ls, alpha=0.4)
            ax.text(b[0], q, f" {int(q*100)}%", fontsize=7, va="bottom", alpha=0.5)
    fig.suptitle("Latency CDF: baseline vs optimized", fontsize=14, y=1.00)
    fig.tight_layout()
    out = FIG_DIR / "cdf.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---- 3. speedup histogram ---------------------------------------------------

def fig_speedup_hist(base, post):
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for (plat, ds), ax in zip(
        [("windows", "coverage"), ("windows", "perf"),
         ("android", "coverage"), ("android", "perf")], axes.flat):
        b = base[(plat, ds)]; p = post[(plat, ds)]
        common = sorted(set(b) & set(p))
        if not common:
            ax.set_visible(False); continue
        sp = np.array([b[s] / max(1, p[s]) for s in common])
        # log-spaced bins
        edges = np.concatenate([
            np.logspace(np.log10(0.3), np.log10(0.99), 8, endpoint=False),
            np.logspace(0, np.log10(50), 20),
        ])
        ax.hist(sp, bins=edges, color="#1a73e8", alpha=0.85, edgecolor="white", linewidth=0.4)
        ax.axvline(1.0, color="black", linestyle="--", linewidth=1, label="no change")
        ax.set_xscale("log")
        ax.set_xlabel("speedup (baseline / optimized, log)")
        ax.set_ylabel("# cases")
        n_regr = int((sp < 0.8).sum())
        n_win  = int((sp > 1.2).sum())
        ax.set_title(f"{plat} / {ds}  (n={len(common)})  wins={n_win}  regr={n_regr}")
        ax.grid(axis="y", which="both", alpha=0.3)
        ax.legend(loc="upper left")
        # x ticks
        ticks = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
        ax.set_xticks(ticks); ax.set_xticklabels([f"{t}x" for t in ticks])
    fig.suptitle("Per-case speedup distribution (baseline / optimized)", fontsize=14, y=1.00)
    fig.tight_layout()
    out = FIG_DIR / "speedup_hist.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---- 4. scatter -------------------------------------------------------------

def fig_scatter(base, post):
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for (plat, ds), ax in zip(
        [("windows", "coverage"), ("windows", "perf"),
         ("android", "coverage"), ("android", "perf")], axes.flat):
        b = base[(plat, ds)]; p = post[(plat, ds)]
        common = sorted(set(b) & set(p))
        if not common:
            ax.set_visible(False); continue
        xs = np.array([b[s] for s in common], dtype=float)
        ys = np.array([p[s] for s in common], dtype=float)
        sp = xs / np.clip(ys, 1, None)
        # colors: green wins, gray neutral, red regressions
        colors = np.where(sp > 1.2, "#188038", np.where(sp < 0.8, "#d93025", "#9aa0a6"))
        ax.scatter(xs, ys, c=colors, s=8, alpha=0.5, edgecolors="none")
        lo = min(xs.min(), ys.min(), 1)
        hi = max(xs.max(), ys.max())
        ax.plot([lo, hi], [lo, hi], color="black", linewidth=0.8, alpha=0.6, label="1:1")
        ax.plot([lo, hi], [lo / 2, hi / 2], color="#188038", linewidth=0.6, alpha=0.5, linestyle="--", label="2x faster")
        ax.plot([lo, hi], [lo * 2, hi * 2], color="#d93025", linewidth=0.6, alpha=0.5, linestyle="--", label="2x slower")
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("baseline (us, log)")
        ax.set_ylabel("optimized (us, log)")
        ax.set_title(f"{plat} / {ds}  (n={len(common)})")
        ax.grid(which="both", alpha=0.3)
        ax.legend(loc="upper left", fontsize=8)
    fig.suptitle("Per-case scatter: baseline vs optimized", fontsize=14, y=1.00)
    fig.tight_layout()
    out = FIG_DIR / "scatter.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---- summary table (also printed) ------------------------------------------

def print_summary(base, post):
    print("\n=== Summary (avg us) ===")
    print(f"{'platform':<8} {'dataset':<9} {'n':>5} {'metric':<6} {'baseline':>10} {'optimized':>10} {'speedup':>9}")
    for plat in ("windows", "android"):
        for ds in ("coverage", "perf"):
            b = base[(plat, ds)]; p = post[(plat, ds)]
            common = sorted(set(b) & set(p))
            if not common: continue
            bv = [b[s] for s in common]; pv = [p[s] for s in common]
            for label, mb, mp in [
                ("p50",  percentile(bv, 50),  percentile(pv, 50)),
                ("p95",  percentile(bv, 95),  percentile(pv, 95)),
                ("p99",  percentile(bv, 99),  percentile(pv, 99)),
                ("mean", int(np.mean(bv)),    int(np.mean(pv))),
            ]:
                sp = mb / max(1, mp)
                print(f"{plat:<8} {ds:<9} {len(common):>5} {label:<6} {mb:>10} {mp:>10} {sp:>8.2f}x")


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    base, post = load_all()
    fig_percentiles(base, post)
    fig_cdf(base, post)
    fig_speedup_hist(base, post)
    fig_scatter(base, post)
    print_summary(base, post)


if __name__ == "__main__":
    main()
