#!/usr/bin/env python3
"""
Horizontal bar chart of active WB + IDB housing/urban-renovation
projects by world region, stacked by institution.

Inputs:  outputs/audit/portfolio_audit_with_region.csv
Outputs: outputs/audit/projects_by_region.png / .svg
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "outputs" / "audit" / "portfolio_audit_with_region.csv"
PNG = ROOT / "outputs" / "audit" / "projects_by_region.png"
SVG = ROOT / "outputs" / "audit" / "projects_by_region.svg"

# CGD Data Visualization Style Guide v03 (4.4.23) — categorical palette.
COLORS = {"World Bank": "#006970", "IDB": "#2D99B5", "ADB": "#FFB52C"}
TEAL_BLACK = "#1A272A"
TEAL = "#0B4C5B"


def safe_float(x: str) -> float:
    try:
        return float(x or 0)
    except ValueError:
        return 0.0


def main() -> int:
    rows = [r for r in csv.DictReader(SRC.open()) if r["region"] != "Unknown"]

    by_region = defaultdict(lambda: defaultdict(float))
    n_by_region = defaultdict(int)

    for r in rows:
        reg = r["region"]
        inst = r["institution"]
        by_region[reg][inst] += safe_float(r.get("commitment_usd"))
        n_by_region[reg] += 1

    order = ["World Bank", "IDB", "ADB"]
    regions = sorted(by_region, key=lambda r: sum(by_region[r].values()), reverse=True)

    fig, ax = plt.subplots(figsize=(8.0, 4.6))

    bottoms = [0.0] * len(regions)
    for kind in order:
        heights = [by_region[r].get(kind, 0.0) / 1e9 for r in regions]
        ax.barh(regions, heights, left=bottoms, color=COLORS[kind],
                label=kind, edgecolor="white", linewidth=0.6)
        bottoms = [b + h for b, h in zip(bottoms, heights)]

    ax.invert_yaxis()
    ax.set_xlabel("Commitment, $ billion", color=TEAL, fontsize=11)
    ax.xaxis.set_major_formatter(mtick.FormatStrFormatter("%.1f"))
    ax.tick_params(axis="both", length=0, colors=TEAL_BLACK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(TEAL_BLACK)
    ax.spines["left"].set_color(TEAL_BLACK)

    max_total = max(bottoms) if bottoms else 1.0
    for i, r in enumerate(regions):
        total = bottoms[i]
        n = n_by_region[r]
        proj_word = "project" if n == 1 else "projects"
        ax.text(total + max_total * 0.02, i, f"${total:.2f}B  ({n} {proj_word})",
                va="center", ha="left", fontsize=9)

    ax.set_xlim(0, max_total * 1.25)

    leg = ax.legend(title="Institution", loc="lower center", bbox_to_anchor=(0.5, -0.28),
                    ncol=3, frameon=False, fontsize=9, columnspacing=2.0, handletextpad=0.5)
    leg.get_title().set_color(TEAL)

    ax.text(0.0, 1.0,
            "World Bank + IDB + ADB Active Housing/Urban-Renewal Portfolio:\n"
            "commitment by region and institution",
            transform=fig.transFigure, ha="left", va="top",
            fontsize=13, fontweight="bold", color=TEAL)

    pos = ax.get_position()
    ax.set_position([pos.x0, 0.16, pos.width, 0.80 - 0.16])

    fig.savefig(PNG, dpi=200, bbox_inches="tight")
    fig.savefig(SVG, bbox_inches="tight")
    print(f"Wrote {PNG}")
    print(f"Wrote {SVG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
