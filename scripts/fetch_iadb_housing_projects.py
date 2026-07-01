#!/usr/bin/env python3
"""
Fetch active Inter-American Development Bank (IDB) housing/urban-
renovation projects from IDB's IATI activity files. Companion fetcher
to fetch_wb_housing_projects.py -- together they build the combined
universe for the lead-in-paint audit (see merge_universe.py).

Same IATI-file-based approach as the water-testing IDB pipeline (IDB
has no public projects API): downloads one XML file per country from
webimages.iadb.org, parses it, filters to housing-sector activities,
and writes:

  outputs/universe/iadb_housing_projects.csv   -- one row per project
  outputs/universe/iadb_housing_documents.csv  -- one row per PDF
                                                   document link

DAC 5-digit sector codes (verified against the IATI Sector codelist,
not guessed):
  16030 = Housing policy and administrative management
  16040 = Low-cost housing
  43030 = Urban development and management
  43032 = Urban development

Default universe: 16030 + 16040 (housing-specific). `--include-urban`
adds 43030/43032, which capture broader urban-renewal/slum-upgrading
projects that often include housing rehabilitation but aren't
exclusively about housing.

Usage:
  python3 fetch_iadb_housing_projects.py                 # housing only
  python3 fetch_iadb_housing_projects.py --include-urban  # + urban dev
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "universe"

IATI_BASE = "https://webimages.iadb.org/iati"

COUNTRY_FILES = {
    "Argentina": "iadb-Argentina.xml",
    "Bahamas": "iadb-Bahamas.xml",
    "Barbados": "iadb-Barbados.xml",
    "Belize": "iadb-Belize.xml",
    "Bolivia": "iadb-Bolivia.xml",
    "Brazil": "iadb-Brazil.xml",
    "Chile": "iadb-Chile.xml",
    "Colombia": "iadb-Colombia.xml",
    "Costa Rica": "iadb-Costa-Rica.xml",
    "Dominican Republic": "iadb-Dominican-Republic.xml",
    "Ecuador": "iadb-Ecuador.xml",
    "El Salvador": "iadb-El-Salvador.xml",
    "Guatemala": "iadb-Guatemala.xml",
    "Guyana": "iadb-Guyana.xml",
    "Haiti": "iadb-Haiti.xml",
    "Honduras": "iadb-Honduras.xml",
    "Jamaica": "iadb-Jamaica.xml",
    "Mexico": "iadb-Mexico.xml",
    "Nicaragua": "iadb-Nicaragua.xml",
    "Panama": "iadb-Panama.xml",
    "Paraguay": "iadb-Paraguay.xml",
    "Peru": "iadb-Peru.xml",
    "Regional": "iadb-Regional.xml",
    "Suriname": "iadb-Suriname.xml",
    "Trinidad and Tobago": "iadb-Trinidad-and-Tobago.xml",
    "Uruguay": "iadb-Uruguay.xml",
    "Venezuela": "iadb-Venezuela.xml",
}

HOUSING_CODES = {"16030", "16040"}
URBAN_CODES = {"43030", "43032"}

STATUS_NAMES = {
    "1": "Pipeline", "2": "Implementation", "3": "Finalisation",
    "4": "Closed", "5": "Cancelled", "6": "Suspended",
}

CACHE_DIR = ROOT / ".iati_cache"


def fetch_country_xml(country: str, filename: str, refresh: bool) -> Path | None:
    CACHE_DIR.mkdir(exist_ok=True)
    dest = CACHE_DIR / filename
    if dest.exists() and not refresh:
        return dest
    url = f"{IATI_BASE}/{filename}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; CGD-research-script/1.0)"}
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=180)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return dest
        except requests.RequestException as e:
            print(f"  !! {country}: attempt {attempt+1} failed: {e}", file=sys.stderr)
            time.sleep(3)
    print(f"  !! {country}: giving up after 3 attempts", file=sys.stderr)
    return None


def transaction_amount(activity, type_code: str) -> float:
    total = 0.0
    for t in activity.findall("transaction"):
        tt = t.find("transaction-type")
        if tt is None or tt.get("code") != type_code:
            continue
        v = t.find("value")
        if v is None or not v.text:
            continue
        try:
            total += float(v.text)
        except ValueError:
            pass
    return total


def budget_amount(activity) -> float:
    total = 0.0
    for b in activity.findall("budget/value"):
        if not b.text:
            continue
        try:
            total += float(b.text)
        except ValueError:
            pass
    return total


def best_commitment(activity) -> float:
    commit = transaction_amount(activity, "2")
    return commit if commit > 0 else budget_amount(activity)


def parse_country_file(path: Path, country: str, target_codes: set[str], status_filter: set[str]):
    parser = etree.XMLParser(recover=True, huge_tree=True)
    try:
        root = etree.parse(str(path), parser).getroot()
    except etree.XMLSyntaxError as e:
        print(f"  !! {country}: XML parse failed: {e}", file=sys.stderr)
        return [], []

    project_rows = []
    doc_rows = []

    for activity in root.findall("iati-activity"):
        iid_el = activity.find("iati-identifier")
        if iid_el is None or not iid_el.text:
            continue
        iati_id = iid_el.text.strip()

        sector_codes = {
            s.get("code") for s in activity.findall("sector")
            if s.get("code") and s.get("vocabulary", "1") == "1"
        }
        if not (sector_codes & target_codes):
            continue

        status_el = activity.find("activity-status")
        status_code = status_el.get("code") if status_el is not None else "?"
        if status_filter and status_code not in status_filter:
            continue

        title_el = activity.find("title/narrative")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""

        approval_date = ""
        for date_type in ("2", "1"):
            d = activity.find(f"activity-date[@type='{date_type}']")
            if d is not None and d.get("iso-date"):
                approval_date = d.get("iso-date")
                break

        commitment = best_commitment(activity)
        docs = activity.findall("document-link")

        project_rows.append({
            "Institution": "IDB",
            "Project_ID": iati_id,
            "Project_Name": title,
            "Country": country,
            "Status": STATUS_NAMES.get(status_code, status_code),
            "Approval_Date": approval_date,
            "Total_Commitment_USD": f"{commitment:.0f}",
            "Sector_Codes": ",".join(sorted(sector_codes)),
        })

        for d in docs:
            fmt = d.get("format") or ""
            if fmt != "application/pdf":
                continue
            url = d.get("url") or ""
            if not url:
                continue
            title_d_el = d.find("title/narrative")
            doc_rows.append({
                "Institution": "IDB",
                "Project_ID": iati_id,
                "Country": country,
                "Doc_Title": title_d_el.text.strip() if title_d_el is not None and title_d_el.text else "",
                "URL": url,
            })

    return project_rows, doc_rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--include-urban", action="store_true",
                     help="Also include urban-development codes (43030/43032)")
    ap.add_argument("--status", default="1,2,3")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out-projects", default=str(OUT_DIR / "iadb_housing_projects.csv"))
    ap.add_argument("--out-documents", default=str(OUT_DIR / "iadb_housing_documents.csv"))
    args = ap.parse_args()

    target_codes = set(HOUSING_CODES)
    if args.include_urban:
        target_codes |= URBAN_CODES
    status_filter = {s.strip() for s in args.status.split(",") if s.strip()}

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_projects = []
    all_docs = []
    seen_ids = set()

    for country, filename in sorted(COUNTRY_FILES.items()):
        print(f"[{country}] fetching {filename}...", file=sys.stderr)
        path = fetch_country_xml(country, filename, args.refresh)
        if path is None:
            continue
        projects, docs = parse_country_file(path, country, target_codes, status_filter)
        for p in projects:
            if p["Project_ID"] in seen_ids:
                continue
            seen_ids.add(p["Project_ID"])
            all_projects.append(p)
        all_docs.extend(d for d in docs if d["Project_ID"] in seen_ids)
        print(f"  -> {len(projects)} housing-sector projects", file=sys.stderr)

    proj_path = Path(args.out_projects)
    with proj_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "Institution", "Project_ID", "Project_Name", "Country", "Status",
            "Approval_Date", "Total_Commitment_USD", "Sector_Codes",
        ])
        w.writeheader()
        w.writerows(all_projects)

    kept_ids = {p["Project_ID"] for p in all_projects}
    docs_path = Path(args.out_documents)
    with docs_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Institution", "Project_ID", "Country", "Doc_Title", "URL"])
        w.writeheader()
        w.writerows(d for d in all_docs if d["Project_ID"] in kept_ids)

    status_tally = defaultdict(int)
    for p in all_projects:
        status_tally[p["Status"]] += 1
    total_commit = sum(float(p["Total_Commitment_USD"]) for p in all_projects) / 1e9

    print(f"\nWrote {proj_path} ({len(all_projects)} projects)")
    print(f"Wrote {docs_path} ({sum(1 for d in all_docs if d['Project_ID'] in kept_ids)} document links)")
    print(f"Status breakdown: {dict(status_tally)}")
    print(f"Total commitment: ${total_commit:.2f}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
