#!/usr/bin/env python3
"""
Fetch active World Bank housing/urban-renovation projects from the WB
Projects API. Companion fetcher to fetch_iadb_housing_projects.py —
together they build the combined universe for the lead-in-paint audit
(see merge_universe.py).

Sector codes (verified against the WB API's sector-name facet, not
guessed — WB uses its own 2/3-letter scheme, not OECD DAC codes):
  YYH = Housing Construction (modern taxonomy)
  YH  = Housing Construction (legacy taxonomy — much larger population,
        same pattern as WWC vs WC in the water-testing pipeline)

Default universe: YYH only, Active. `--include-legacy` adds YH,
mirroring the "strictest filter first, widen only with justification"
principle used throughout this project family.

Usage:
  python3 fetch_wb_housing_projects.py                    # YYH only (default)
  python3 fetch_wb_housing_projects.py --include-legacy    # YYH + YH
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "universe"

API_URL = "https://search.worldbank.org/api/v3/projects"
ROWS_PER_PAGE = 200

FIELDS = [
    "id", "project_name", "countryshortname", "boardapprovaldate",
    "projectstatusdisplay", "status", "totalcommamt", "totalamt",
    "curr_ibrd_commitment", "curr_ida_commitment", "grantamt", "sectorcode",
]

HOUSING_MODERN = "YYH"
HOUSING_LEGACY = "YH"


def fetch_page(sector_code: str, offset: int, active_only: bool, retries: int = 4) -> dict:
    params = {
        "format": "json", "rows": ROWS_PER_PAGE, "os": offset,
        "fl": ",".join(FIELDS), "sectorcode": sector_code,
    }
    if active_only:
        params["projectstatusdisplay_exact"] = "Active"
    delay = 1.0
    for attempt in range(retries):
        try:
            r = requests.get(API_URL, params=params, timeout=60)
            if r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} server error")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt+1}/{retries} after {delay:.1f}s: {e}", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def iter_projects(sector_code: str, active_only: bool):
    offset = 0
    while True:
        payload = fetch_page(sector_code, offset, active_only)
        total = int(payload.get("total", 0))
        projects = payload.get("projects") or {}
        if not projects:
            return
        for _, rec in projects.items():
            yield rec
        offset += ROWS_PER_PAGE
        if offset >= total:
            return
        time.sleep(0.3)


def sector_codes(rec: dict) -> set[str]:
    raw = rec.get("sectorcode") or ""
    return {c.strip() for c in raw.split(",") if c.strip()}


def commitment_usd(rec: dict) -> float:
    for key in ("totalcommamt", "totalamt"):
        v = rec.get(key)
        if v not in (None, "", "0"):
            try:
                return float(v)
            except ValueError:
                pass
    total = 0.0
    for key in ("curr_ibrd_commitment", "curr_ida_commitment", "grantamt"):
        try:
            total += float(rec.get(key) or 0)
        except ValueError:
            pass
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT_DIR / "wb_housing_projects.csv"))
    ap.add_argument("--include-legacy", action="store_true",
                     help="Add YH (legacy Housing Construction code) to the universe")
    ap.add_argument("--all-status", action="store_true")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    target_sectors = [HOUSING_MODERN, HOUSING_LEGACY] if args.include_legacy else [HOUSING_MODERN]
    active_only = not args.all_status
    print(f"Sectors: {target_sectors}   active_only={active_only}", file=sys.stderr)

    seen: dict[str, dict] = {}
    for code in target_sectors:
        n_before = len(seen)
        for rec in iter_projects(code, active_only):
            pid = rec.get("id")
            if pid and pid not in seen:
                seen[pid] = rec
        print(f"  after sector {code}: {len(seen)} unique projects (+{len(seen) - n_before})", file=sys.stderr)

    rows = list(seen.values())
    rows.sort(key=commitment_usd, reverse=True)

    out_path = Path(args.out)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Institution", "Project_ID", "Project_Name", "Country", "Approval_Date",
                    "Status", "Total_Commitment_USD", "Sector_Codes"])
        for rec in rows:
            w.writerow([
                "World Bank",
                rec.get("id", ""),
                rec.get("project_name", ""),
                rec.get("countryshortname", ""),
                (rec.get("boardapprovaldate") or "")[:10],
                rec.get("projectstatusdisplay") or rec.get("status", ""),
                int(commitment_usd(rec)),
                ",".join(sorted(sector_codes(rec))),
            ])
    print(f"\nWrote {out_path} ({len(rows)} projects)", file=sys.stderr)

    total_usd = sum(commitment_usd(r) for r in rows)
    print(f"Total commitment: ${total_usd/1e9:,.2f} B")
    print(f"\nTop {args.top} by commitment:")
    for rec in rows[:args.top]:
        amt = commitment_usd(rec)
        print(f"  {rec.get('id','?'):10s} {rec.get('countryshortname','?'):25s} ${amt/1e6:>7,.0f} M  {rec.get('project_name','')[:50]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
