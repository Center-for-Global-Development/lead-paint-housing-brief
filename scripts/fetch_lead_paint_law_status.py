#!/usr/bin/env python3
"""
Fetch WHO's "Legally-binding controls on lead paint" indicator
(LEADCONTROL) from the WHO Global Health Observatory API, and map it
onto the countries in our combined housing-project universe.

Why this matters for the audit
-------------------------------
A bank project that doesn't test for lead paint is a bigger gap in a
country with no domestic legal limit on lead in paint (no regulatory
backstop at all) than in a country that already bans/limits lead paint
by law -- there, the bank's silence is backstopped by the national
market not legally selling lead paint in the first place (assuming the
law is enforced; see caveat below).

**Important caveat: this indicator tracks legal existence, not
enforcement quality.** WHO's own data collection is a survey of
whether a country has passed a binding limit -- it does not assess
whether that limit is actually enforced, whether informal/small-batch
paint manufacturers comply, or whether imported paint is tested at the
border. A "Yes" here should be read as "a law exists" not "consumers
are protected in practice." Multiple studies (IPEN paint-testing
surveys in particular) have found lead paint on store shelves in
countries that already have a legal limit on the books. Treat this as
a lower bound on the regulatory backstop, not a certificate of safety.

Source: WHO Global Health Observatory OData API, indicator LEADCONTROL
        https://ghoapi.azureedge.net/api/LEADCONTROL
Data vintage: most recent government submissions as of 31 March 2023
        (per the indicator's own "Comments" field), API-queried at
        pipeline build time.

Outputs
-------
    outputs/reference/who_lead_paint_law_status.csv
        one row per country in our universe: Country, ISO3,
        Law_Status (Yes / No / No data), Lead_Limit_Comment (WHO's
        free-text description of the limit/scope, when Law_Status=Yes)

Usage:
    python3 fetch_lead_paint_law_status.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "reference"
UNIVERSE_CSV = ROOT / "outputs" / "universe" / "combined_housing_projects.csv"

WHO_API = "https://ghoapi.azureedge.net/api/LEADCONTROL"

# Country name (as it appears in our project data) -> ISO3 code (as WHO
# GHO's SpatialDim uses). Only countries that actually appear in the
# combined housing universe need an entry here; "Regional" and WB's
# multi-country aggregate labels ("Eastern and Southern Africa",
# "Western and Central Africa") have no single-country law status and
# are left unmapped on purpose.
COUNTRY_TO_ISO3 = {
    "Armenia": "ARM", "Belize": "BLZ", "Brazil": "BRA", "Cameroon": "CMR",
    "Croatia": "HRV", "El Salvador": "SLV", "Maldives": "MDV",
    "Pakistan": "PAK", "Serbia": "SRB", "Ukraine": "UKR",
    "Argentina": "ARG", "Ecuador": "ECU", "Mexico": "MEX", "Panama": "PAN",
    "Paraguay": "PRY", "Peru": "PER", "Suriname": "SUR",
    "Trinidad and Tobago": "TTO", "Uruguay": "URY",
    "China": "CHN", "India": "IND", "Indonesia": "IDN", "Mongolia": "MNG",
    "Myanmar": "MMR", "Philippines": "PHL", "Kazakhstan": "KAZ",
    "Kyrgyz Republic": "KGZ", "Uzbekistan": "UZB", "Bangladesh": "BGD",
    "Bhutan": "BTN",
}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    resp = requests.get(WHO_API, timeout=60)
    resp.raise_for_status()
    rows = resp.json()["value"]
    by_iso = {r["SpatialDim"]: r for r in rows}

    universe_countries = set()
    if UNIVERSE_CSV.exists():
        with UNIVERSE_CSV.open() as f:
            for row in csv.DictReader(f):
                universe_countries.add(row["Country"])

    out_rows = []
    unmapped = []
    for country in sorted(universe_countries):
        iso3 = COUNTRY_TO_ISO3.get(country)
        if iso3 is None:
            unmapped.append(country)
            continue
        who_row = by_iso.get(iso3)
        if who_row is None:
            out_rows.append({"Country": country, "ISO3": iso3, "Law_Status": "No data", "Lead_Limit_Comment": ""})
            continue
        out_rows.append({
            "Country": country,
            "ISO3": iso3,
            "Law_Status": who_row["Value"] or "No data",
            "Lead_Limit_Comment": who_row.get("Comments") or "",
        })

    out_path = OUT_DIR / "who_lead_paint_law_status.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Country", "ISO3", "Law_Status", "Lead_Limit_Comment"])
        w.writeheader()
        w.writerows(out_rows)

    print(f"Wrote {out_path} ({len(out_rows)} countries)")
    if unmapped:
        print(f"  ! Countries in the universe with no ISO3 mapping (multi-country "
              f"aggregates or missing from COUNTRY_TO_ISO3): {sorted(unmapped)}", file=sys.stderr)

    import collections
    tally = collections.Counter(r["Law_Status"] for r in out_rows)
    print(f"Law status distribution: {dict(tally)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
