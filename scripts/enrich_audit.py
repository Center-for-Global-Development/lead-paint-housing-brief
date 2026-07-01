#!/usr/bin/env python3
"""
Enrich portfolio_audit.csv with a world-region column for the combined
WB + IDB chart.

Pure local lookup, no API calls -- the combined universe spans a small,
enumerable set of countries (IDB's is Latin America/Caribbean only; the
World Bank housing universe adds a handful of countries elsewhere).

Inputs:  outputs/audit/portfolio_audit.csv
Outputs: outputs/audit/portfolio_audit_with_region.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT / "outputs" / "audit"

REGION = {
    "Argentina": "Latin America & Caribbean", "Belize": "Latin America & Caribbean",
    "Brazil": "Latin America & Caribbean", "Ecuador": "Latin America & Caribbean",
    "El Salvador": "Latin America & Caribbean", "Mexico": "Latin America & Caribbean",
    "Panama": "Latin America & Caribbean", "Paraguay": "Latin America & Caribbean",
    "Peru": "Latin America & Caribbean", "Suriname": "Latin America & Caribbean",
    "Trinidad and Tobago": "Latin America & Caribbean", "Uruguay": "Latin America & Caribbean",
    "Armenia": "Europe & Central Asia", "Croatia": "Europe & Central Asia",
    "Serbia": "Europe & Central Asia", "Ukraine": "Europe & Central Asia",
    "Pakistan": "South Asia", "Maldives": "South Asia", "Bangladesh": "South Asia",
    "Bhutan": "South Asia", "India": "South Asia",
    "Cameroon": "Sub-Saharan Africa",
    "Eastern and Southern Africa": "Sub-Saharan Africa",
    "Western and Central Africa": "Sub-Saharan Africa",
    "China": "East Asia & Pacific", "Indonesia": "East Asia & Pacific",
    "Mongolia": "East Asia & Pacific", "Myanmar": "East Asia & Pacific",
    "Philippines": "East Asia & Pacific",
    "Kazakhstan": "Europe & Central Asia", "Kyrgyz Republic": "Europe & Central Asia",
    "Uzbekistan": "Europe & Central Asia",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="audit_in", default=str(AUDIT_DIR / "portfolio_audit.csv"))
    ap.add_argument("--out", dest="audit_out", default=str(AUDIT_DIR / "portfolio_audit_with_region.csv"))
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.audit_in)))
    if not rows:
        print(f"No rows in {args.audit_in}")
        return 1

    for r in rows:
        r["region"] = REGION.get(r["country"], "Unknown")

    fieldnames = list(rows[0].keys())
    with open(args.audit_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    by_region = Counter(r["region"] for r in rows)
    print(f"Wrote {args.audit_out}")
    print(f"Region distribution: {dict(by_region)}")
    if "Unknown" in by_region:
        print("  ! Some countries not in the REGION lookup — add them.")
        for r in rows:
            if r["region"] == "Unknown":
                print(f"      {r['country']} ({r['project_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
