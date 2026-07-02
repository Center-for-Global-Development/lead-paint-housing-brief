#!/usr/bin/env python3
"""
World map of MDB housing/urban-renewal projects, coloured by lead-paint
risk tier for the project's country.

Combines three data sources built earlier in the pipeline:
  - outputs/universe/combined_housing_projects.csv  (project counts, $ by country)
  - outputs/reference/who_lead_paint_law_status.csv  (legal limit: Yes/No/No data)
  - outputs/reference/paint_market_surveys.csv       (independent market-testing
                                                        results, where they exist)

Risk tiers (highest to lowest concern)
---------------------------------------
  1. No legal limit          -- confirmed no domestic law restricting lead in paint
  2. Legal limit not met     -- a law exists, but independent market testing found
                                 lead paint for sale above the legal threshold
  3. Legal limit, untested   -- a law exists; no market survey in our reference
                                 table to check whether it's actually met
  4. No data                 -- WHO has no law-status record for this country, or
                                 it's a World Bank multi-country regional operation
                                 with no single country to categorise

Tier 2 is deliberately distinct from tier 1: a country with a law that market
testing shows is being violated is a different (arguably more specific, since
we have direct evidence rather than an inference) finding than a country with
no law at all. Collapsing them would lose that distinction.

Outputs
-------
    outputs/audit/lead_paint_risk_map.png   (static, for the write-up)
    outputs/audit/lead_paint_risk_map.html  (interactive, hover for detail)

Usage:
    python3 plot_lead_paint_risk_map.py
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
COMBINED = ROOT / "outputs" / "universe" / "combined_housing_projects.csv"
LAW_STATUS = ROOT / "outputs" / "reference" / "who_lead_paint_law_status.csv"
MARKET_SURVEYS = ROOT / "outputs" / "reference" / "paint_market_surveys.csv"
OUT_PNG = ROOT / "outputs" / "audit" / "lead_paint_risk_map.png"
OUT_HTML = ROOT / "outputs" / "audit" / "lead_paint_risk_map.html"

# CGD Data Visualization Style Guide v03 (4.4.23) categorical palette,
# extended with two additional greys/reds for the four-tier risk scale.
TIER_COLORS = {
    "No legal limit":        "#B2182B",  # red -- highest concern
    "Legal limit not met":   "#FFB52C",  # CGD gold -- law exists, evidence of violation
    "Legal limit, untested": "#2D99B5",  # CGD blue -- law exists, no market check
    "No data":               "#B0B0B0",  # grey -- can't assess
}
TIER_ORDER = ["No legal limit", "Legal limit not met", "Legal limit, untested", "No data"]

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


def load_law_status() -> dict[str, dict]:
    out = {}
    if not LAW_STATUS.exists():
        return out
    with LAW_STATUS.open() as f:
        for row in csv.DictReader(f):
            out[row["Country"]] = {"iso3": row["ISO3"], "status": row["Law_Status"]}
    return out


def load_market_survey_max_pct() -> dict[str, float]:
    """Highest reported exceedance percentage per country, across all
    survey rows for that country (different cities/paint types/years)."""
    out: dict[str, float] = {}
    if not MARKET_SURVEYS.exists():
        return out
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
    # law_status == "Yes"
    if has_market_evidence:
        return "Legal limit not met"
    return "Legal limit, untested"


def main() -> int:
    projects = load_project_totals()
    law = load_law_status()
    market = load_market_survey_max_pct()

    rows = []
    for country, p in projects.items():
        law_rec = law.get(country)
        iso3 = law_rec["iso3"] if law_rec else None
        status = law_rec["status"] if law_rec else None
        has_market = country in market
        tier = classify_tier(status, has_market)

        if iso3 is None:
            # World Bank multi-country regional aggregates ("Eastern and
            # Southern Africa", etc.) have no single country to plot.
            continue

        rows.append({
            "country": country,
            "iso3": iso3,
            "tier": tier,
            "law_status": status or "No data",
            "n_projects": p["n"],
            "commitment_b": p["commitment_usd"] / 1e9,
            "institutions": ", ".join(sorted(p["institutions"])),
            "market_pct": market.get(country),
        })

    # One trace per tier so the legend is categorical, not a continuous scale.
    fig = go.Figure()
    for tier in TIER_ORDER:
        tier_rows = [r for r in rows if r["tier"] == tier]
        if not tier_rows:
            continue
        fig.add_trace(go.Choropleth(
            locations=[r["iso3"] for r in tier_rows],
            z=[1] * len(tier_rows),
            locationmode="ISO-3",
            colorscale=[[0, TIER_COLORS[tier]], [1, TIER_COLORS[tier]]],
            showscale=False,
            showlegend=True,
            name=tier,
            marker_line_color="white",
            marker_line_width=0.5,
            customdata=[[r["country"], r["n_projects"], f"{r['commitment_b']:.2f}",
                        r["institutions"], r["law_status"],
                        f"{r['market_pct']:.0f}%" if r["market_pct"] is not None else "no data"]
                       for r in tier_rows],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Projects: %{customdata[1]} (%{customdata[3]})<br>"
                "Commitment: $%{customdata[2]}B<br>"
                "Lead-paint law: %{customdata[4]}<br>"
                "Market testing found exceeding limit: %{customdata[5]}"
                "<extra></extra>"
            ),
        ))

    fig.update_layout(
        title=dict(
            text="<b>Where MDB housing projects sit relative to lead-paint risk</b><br>"
                 "<sup>World Bank + IDB + ADB active projects, by country lead-paint-law "
                 "status and market-testing evidence</sup>",
            font=dict(color=TEAL, size=16),
            x=0.01, xanchor="left",
        ),
        geo=dict(
            showframe=False,
            showcoastlines=True,
            coastlinecolor="#DDDDDD",
            projection_type="natural earth",
            landcolor="#F0F0F0",
            showcountries=True,
            countrycolor="#DDDDDD",
        ),
        legend=dict(
            title=dict(text="Lead-paint risk tier", font=dict(color=TEAL)),
            orientation="h", yanchor="top", y=-0.02, xanchor="center", x=0.5,
        ),
        margin=dict(l=10, r=10, t=90, b=110),
        annotations=[dict(
            text="Red and gold are confirmed lead-paint exposure risk. \"Untested\" (blue) means a law exists but isn't market-checked here.",
            showarrow=False, x=0.5, y=-0.14, xref="paper", yref="paper",
            font=dict(size=12, color="#555555"), align="center",
        )],
    )

    # CDN mode instead of the default inline bundle -- shrinks the
    # committed file from ~4.9MB to a few KB. Requires network access to
    # view (loads plotly.js from a CDN), which is a reasonable trade for
    # a repo file.
    fig.write_html(str(OUT_HTML), include_plotlyjs="cdn")
    fig.write_image(str(OUT_PNG), width=1600, height=950, scale=2)

    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_HTML}")

    from collections import Counter
    tier_counts = Counter(r["tier"] for r in rows)
    print(f"\nCountries by risk tier: {dict(tier_counts)}")
    excluded = [c for c in projects if c not in {r["country"] for r in rows}]
    if excluded:
        print(f"Excluded (no ISO3 -- multi-country regional aggregates): {excluded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
