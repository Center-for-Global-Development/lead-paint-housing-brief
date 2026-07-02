#!/usr/bin/env python3
"""
Horizontal bar chart of every country with an active WB/IDB/ADB housing
project, sorted by lead-paint risk tier and coloured to match, with
project count and market-survey evidence labelled on each bar.

Same underlying data and four-tier risk classification as
plot_lead_paint_risk_map.py (see that script's docstring for the tier
definitions and the "no law vs. law-not-met" distinction) -- this is
an alternative, more precise presentation: a map's colour is easy to
misjudge at a glance, and it wastes space on the ~170 countries with
no MDB housing project at all. A sorted bar chart puts every country
on a comparable axis and can label the exact market-survey percentage
inline, which a map can only show on hover.

Inputs:  outputs/universe/combined_housing_projects.csv
         outputs/reference/who_lead_paint_law_status.csv
         outputs/reference/paint_market_surveys.csv
Outputs: outputs/audit/lead_paint_risk_bars.png / .svg
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

ROOT = Path(__file__).resolve().parent.parent
COMBINED = ROOT / "outputs" / "universe" / "combined_housing_projects.csv"
LAW_STATUS = ROOT / "outputs" / "reference" / "who_lead_paint_law_status.csv"
MARKET_SURVEYS = ROOT / "outputs" / "reference" / "paint_market_surveys.csv"
OUT_PNG = ROOT / "outputs" / "audit" / "lead_paint_risk_bars.png"
OUT_SVG = ROOT / "outputs" / "audit" / "lead_paint_risk_bars.svg"

# Same palette as plot_lead_paint_risk_map.py, so the two figures read
# as a matched pair if both are used.
TIER_COLORS = {
    "No legal limit":        "#B2182B",
    "Legal limit not met":   "#FFB52C",
    "Legal limit, untested": "#2D99B5",
    "No data":               "#B0B0B0",
}
TIER_PRIORITY = {"No legal limit": 3, "Legal limit not met": 2, "Legal limit, untested": 1, "No data": 0}

# Short institution codes for the per-bar labels -- ADB/IDB/WB rather
# than bare first-letter initials (A/I/W), so the label is legible
# without having to infer what each letter stands for.
INSTITUTION_ABBR = {"World Bank": "WB", "IDB": "IDB", "ADB": "ADB"}

TEAL_BLACK = "#1A272A"
TEAL = "#0B4C5B"


def load_project_totals() -> dict[str, dict]:
    by_country = defaultdict(lambda: {"n": 0, "commitment_usd": 0.0, "institutions": set()})
    with COMBINED.open() as f:
        for row in csv.DictReader(f):
            c = row["Country"]
            by_country[c]["n"] += 1
            by_country[c]["commitment_usd"] += float(row.get("Total_Commitment_USD") or 0)
            by_country[c]["institutions"].add(row["Institution"])
    return by_country


def load_law_status() -> dict[str, str]:
    out = {}
    if LAW_STATUS.exists():
        with LAW_STATUS.open() as f:
            for row in csv.DictReader(f):
                out[row["Country"]] = row["Law_Status"]
    return out


def load_market_survey_max_pct() -> dict[str, float]:
    out: dict[str, float] = {}
    if MARKET_SURVEYS.exists():
        with MARKET_SURVEYS.open() as f:
            for row in csv.DictReader(f):
                c = row["Country"]
                pct_str = (row.get("Pct_Exceeding_Limit") or "").rstrip("%")
                if not pct_str:
                    continue
                try:
                    pct = float(pct_str)
                except ValueError:
                    continue
                out[c] = max(out.get(c, 0.0), pct)
    return out


def classify_tier(law_status: str | None, has_market_evidence: bool) -> str:
    if law_status is None or law_status == "No data":
        return "No data"
    if law_status == "No":
        return "No legal limit"
    return "Legal limit not met" if has_market_evidence else "Legal limit, untested"


def main() -> int:
    projects = load_project_totals()
    law = load_law_status()
    market = load_market_survey_max_pct()

    rows = []
    for country, p in projects.items():
        status = law.get(country)
        has_market = country in market
        tier = classify_tier(status, has_market)
        rows.append({
            "country": country,
            "tier": tier,
            "law_status": status or "No data",
            "n": p["n"],
            "commitment_b": p["commitment_usd"] / 1e9,
            "institutions": "+".join(sorted(INSTITUTION_ABBR.get(inst, inst) for inst in p["institutions"])),
            "market_pct": market.get(country),
        })

    # Sort by tier severity (worst first), then by commitment within tier.
    rows.sort(key=lambda r: (TIER_PRIORITY[r["tier"]], r["commitment_b"]), reverse=True)
    # Reverse again so barh (which plots bottom-to-top) reads worst-tier-on-top.
    rows = rows[::-1]

    fig, ax = plt.subplots(figsize=(9.0, 10.5))

    labels = [r["country"] for r in rows]
    heights = [r["commitment_b"] for r in rows]
    colors = [TIER_COLORS[r["tier"]] for r in rows]

    ax.barh(labels, heights, color=colors, edgecolor="white", linewidth=0.6)
    ax.margins(y=0.01)

    ax.set_xlabel("Commitment, $ billion", color=TEAL, fontsize=11)
    ax.xaxis.set_major_formatter(mtick.FormatStrFormatter("%.1f"))
    ax.tick_params(axis="both", length=0, colors=TEAL_BLACK)
    ax.tick_params(axis="y", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(TEAL_BLACK)
    ax.spines["left"].set_color(TEAL_BLACK)

    max_val = max(heights) if heights else 1.0
    for i, r in enumerate(rows):
        label = f"{r['n']} proj ({r['institutions']})"
        if r["market_pct"] is not None:
            label += f"  — {r['market_pct']:.0f}% of tested paint over limit"
        ax.text(r["commitment_b"] + max_val * 0.02, i, label,
                va="center", ha="left", fontsize=8, color=TEAL_BLACK)

    ax.set_xlim(0, max_val * 1.9)

    handles = [plt.Rectangle((0, 0), 1, 1, color=TIER_COLORS[t]) for t in TIER_COLORS]
    leg = ax.legend(handles, list(TIER_COLORS.keys()), title="Lead-paint risk tier",
                    loc="lower right", frameon=False, fontsize=9)
    leg.get_title().set_color(TEAL)

    ax.text(0.0, 1.0,
            "Where MDB housing projects sit relative to lead-paint risk\n"
            "By country, sorted by risk tier then commitment",
            transform=fig.transFigure, ha="left", va="top",
            fontsize=13, fontweight="bold", color=TEAL)

    fig.text(0.5, 0.005,
             "\"Legal limit not met\" = independent market survey found lead paint for sale "
             "above the legal threshold. \"Untested\" = a law exists but our reference table "
             "has no market survey for that country.",
             ha="center", fontsize=8.5, style="italic", color=TEAL_BLACK)

    pos = ax.get_position()
    ax.set_position([pos.x0, 0.06, pos.width, 0.93 - 0.06])

    fig.savefig(OUT_PNG, dpi=200, bbox_inches="tight")
    fig.savefig(OUT_SVG, bbox_inches="tight")
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_SVG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
