#!/usr/bin/env python3
"""
Enrich portfolio_audit.csv with a world-region column and the WHO
lead-paint-law status for the project's country.

The law-status join answers a question the raw verdict can't: a
project that doesn't test for lead paint matters more in a country
with no domestic legal limit on lead in paint (no backstop at all)
than in one that already has a law on the books -- even though that
law-existence signal says nothing about enforcement (see
fetch_lead_paint_law_status.py for the caveat in full).

Pure local lookup, no API calls at enrich time -- the combined universe
spans a small, enumerable set of countries (IDB's is Latin
America/Caribbean only; the World Bank and ADB housing universes add
countries elsewhere), and the WHO law-status data was already fetched
once into outputs/reference/who_lead_paint_law_status.csv by
fetch_lead_paint_law_status.py.

Inputs:  outputs/audit/portfolio_audit.csv
         outputs/reference/who_lead_paint_law_status.csv
Outputs: outputs/audit/portfolio_audit_with_region.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT / "outputs" / "audit"
LAW_STATUS_CSV = ROOT / "outputs" / "reference" / "who_lead_paint_law_status.csv"

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
    ap.add_argument("--law-status", default=str(LAW_STATUS_CSV))
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.audit_in)))
    if not rows:
        print(f"No rows in {args.audit_in}")
        return 1

    law_by_country = {}
    law_path = Path(args.law_status)
    if law_path.exists():
        with law_path.open() as f:
            for r in csv.DictReader(f):
                law_by_country[r["Country"]] = r["Law_Status"]
    else:
        print(f"  ! {law_path} not found -- run fetch_lead_paint_law_status.py first. "
              f"Proceeding without law-status enrichment.")

    for r in rows:
        r["region"] = REGION.get(r["country"], "Unknown")
        r["lead_paint_law_status"] = law_by_country.get(r["country"], "No data")

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

    # Cross-tab: verdict x lead-paint law status. This is the reframing
    # the audit is really after -- how many "no mention" projects sit
    # in countries with no legal backstop at all. Keep "No" (confirmed
    # no law) and "No data" (unknown, or a WB multi-country regional
    # aggregate with no single country to look up) separate -- collapsing
    # them would overstate how many countries are confirmed unregulated.
    print("\nVerdict x lead-paint law status (project counts):")
    for status in ["No", "No data", "Yes"]:
        sub = [r for r in rows if r["lead_paint_law_status"] == status]
        if not sub:
            continue
        verdicts = Counter(r["verdict"] for r in sub)
        commit = sum(float(r["commitment_usd"]) for r in sub) / 1e9
        print(f"  {status:<8} n={len(sub):<3} ${commit:.2f}B  verdicts={dict(verdicts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
