#!/usr/bin/env python3
"""
Fetch active Asian Development Bank (ADB) housing/urban-renovation
projects from ADB's IATI activity files. Third fetcher in the combined
lead-in-paint audit (World Bank, IDB, ADB) -- see merge_universe.py.

Like IDB, ADB has no public REST projects API; it publishes one IATI
2.0x XML file per country under adb.org/iati/. Unlike IDB, ADB's
activities are tranche-level (one <iati-activity> per loan/tranche of
a project, sharing a common base project number), so this script
dedupes by the base project ID the same way the ADB water-portfolio
analysis in this project family did.

DAC 5-digit sector codes (same as IDB housing fetcher):
  16030 = Housing policy and administrative management
  16040 = Low-cost housing

Sovereign vs. non-sovereign filtering
--------------------------------------
ADB's housing-sector tag captures both (a) sovereign operations --
government-implemented construction/upgrading programs, which carry
ESIA-type safeguards documents -- and (b) non-sovereign operations --
loans to private housing-finance companies (mortgage lenders, NBFCs),
which are pure financial-intermediary transactions with no
construction component and no ESIA. Including (b) would inflate the
audit's denominator with projects that structurally can never have a
lead-paint testing commitment, since there's no renovation activity to
test in the first place.

IATI signal used to distinguish them: the activity's Implementing
participating-org (role="4"). A type="70" (Private Sector) implementing
org marks a non-sovereign operation; type="10" (Government) or similar
public-sector types mark a sovereign one. Verified against two known
examples: "Shapoorji Affordable Housing Project" (implementing org
type=70, a private developer) vs. "Improving Urban Governance and
Infrastructure Program" (implementing org type=10, a government
department).

Default universe EXCLUDES non-sovereign operations. Pass
--include-non-sovereign to keep them (with a Non_Sovereign column so
they can still be filtered downstream).

Usage:
  python3 fetch_adb_housing_projects.py                      # sovereign only
  python3 fetch_adb_housing_projects.py --include-non-sovereign
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
import csv

import requests
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "universe"

IATI_BASE = "https://www.adb.org/iati"

COUNTRY_FILES = {
    "Afghanistan": "af", "Armenia": "am", "Azerbaijan": "az", "Bangladesh": "bd",
    "Bhutan": "bt", "Cook Islands": "ck", "China": "cn", "Fiji": "fj",
    "Micronesia": "fm", "Georgia": "ge", "Indonesia": "id", "India": "in",
    "Kyrgyz Republic": "kg", "Cambodia": "kh", "Kiribati": "ki", "Kazakhstan": "kz",
    "Laos": "la", "Sri Lanka": "lk", "Marshall Islands": "mh", "Myanmar": "mm",
    "Mongolia": "mn", "Maldives": "mv", "Nepal": "np", "Nauru": "nr",
    "Papua New Guinea": "pg", "Philippines": "ph", "Pakistan": "pk", "Palau": "pw",
    "Regional": "reg", "Solomon Islands": "sb", "Thailand": "th", "Tajikistan": "tj",
    "Timor-Leste": "tl", "Turkmenistan": "tm", "Tonga": "to", "Tuvalu": "tv",
    "Uzbekistan": "uz", "Vietnam": "vn", "Vanuatu": "vu", "Samoa": "ws",
}

HOUSING_CODES = {"16030", "16040"}

STATUS_NAMES = {
    "1": "Pipeline", "2": "Implementation", "3": "Finalisation",
    "4": "Closed", "5": "Cancelled", "6": "Suspended",
}

CACHE_DIR = ROOT / ".iati_cache_adb"

RE_BASE_ID = re.compile(r"46004-(\d{4,6}-\d{3,4})")


def fetch_country_xml(country: str, code: str, refresh: bool) -> Path | None:
    CACHE_DIR.mkdir(exist_ok=True)
    filename = f"iati-activities-{code}.xml"
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


def sanitize_adb_doc_url(url: str) -> str | None:
    """Clean up known data-quality issues in ADB's IATI document-link URLs.

    Two problems observed in the wild, both in ADB's source data (not a
    parsing bug on our end):
      1. Some document-links tagged format="application/pdf" actually
         point to project landing pages (".../projects/NNNNN/main" or
         with a "#project-tenders" fragment) rather than a PDF.
      2. A handful of entries have two URLs run together with no
         separator, or joined with a semicolon.
    Returns None if the URL should be skipped entirely, otherwise the
    single best URL to fetch.
    """
    if not url:
        return None
    if ";" in url:
        url = url.split(";", 1)[0]
    # Concatenated URLs: a second "https://" partway through the string.
    idx = url.find("https://", 8)
    if idx != -1:
        url = url[:idx]
    if "/main#" in url or url.rstrip("/").endswith("/main"):
        return None
    if not url.lower().endswith(".pdf"):
        return None
    return url


def is_non_sovereign(activity) -> bool:
    for p in activity.findall("participating-org"):
        if p.get("role") == "4" and p.get("type") == "70":
            return True
    return False


def parse_country_file(path: Path, country: str, status_filter: set[str], include_non_sovereign: bool):
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
        if not (sector_codes & HOUSING_CODES):
            continue

        non_sov = is_non_sovereign(activity)
        if non_sov and not include_non_sovereign:
            continue

        status_el = activity.find("activity-status")
        status_code = status_el.get("code") if status_el is not None else "?"
        if status_filter and status_code not in status_filter:
            continue

        title_el = activity.find("title/narrative")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""

        m = RE_BASE_ID.search(iati_id)
        base_id = m.group(1) if m else iati_id

        commitment = transaction_amount(activity, "2")
        docs = activity.findall("document-link")

        project_rows.append({
            "Institution": "ADB",
            "Project_ID": base_id,
            "Project_Name": title,
            "Country": country,
            "Status": STATUS_NAMES.get(status_code, status_code),
            "Approval_Date": "",
            "Total_Commitment_USD": f"{commitment:.0f}",
            "Sector_Codes": ",".join(sorted(sector_codes)),
            "Non_Sovereign": "Yes" if non_sov else "No",
        })

        for d in docs:
            fmt = d.get("format") or ""
            if fmt != "application/pdf":
                continue
            url = sanitize_adb_doc_url(d.get("url") or "")
            if not url:
                continue
            title_d_el = d.find("title/narrative")
            doc_rows.append({
                "Institution": "ADB",
                "Project_ID": base_id,
                "Country": country,
                "Doc_Title": title_d_el.text.strip() if title_d_el is not None and title_d_el.text else "",
                "URL": url,
            })

    return project_rows, doc_rows


def dedupe_by_base_id(rows: list[dict]) -> list[dict]:
    """Collapse tranche-level rows to one row per base project, keeping
    the most 'active' status and summing commitments across tranches."""
    priority = {"Pipeline": 4, "Implementation": 5, "Finalisation": 3, "Closed": 1, "Cancelled": 0, "Suspended": 2}
    by_id: dict[str, dict] = {}
    for r in rows:
        pid = r["Project_ID"]
        if pid not in by_id:
            by_id[pid] = dict(r)
        else:
            prev = by_id[pid]
            prev["Total_Commitment_USD"] = str(float(prev["Total_Commitment_USD"]) + float(r["Total_Commitment_USD"]))
            if priority.get(r["Status"], 0) > priority.get(prev["Status"], 0):
                prev["Status"] = r["Status"]
                prev["Project_Name"] = r["Project_Name"]
    return list(by_id.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--include-non-sovereign", action="store_true",
                     help="Keep non-sovereign (private-sector) housing-finance operations")
    ap.add_argument("--status", default="1,2,3")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out-projects", default=str(OUT_DIR / "adb_housing_projects.csv"))
    ap.add_argument("--out-documents", default=str(OUT_DIR / "adb_housing_documents.csv"))
    args = ap.parse_args()

    status_filter = {s.strip() for s in args.status.split(",") if s.strip()}

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_project_rows = []
    all_docs = []

    for country, code in sorted(COUNTRY_FILES.items()):
        print(f"[{country}] fetching {code}...", file=sys.stderr)
        path = fetch_country_xml(country, code, args.refresh)
        if path is None:
            continue
        projects, docs = parse_country_file(path, country, status_filter, args.include_non_sovereign)
        all_project_rows.extend(projects)
        all_docs.extend(docs)
        print(f"  -> {len(projects)} housing-sector tranche rows", file=sys.stderr)

    merged = dedupe_by_base_id(all_project_rows)
    kept_ids = {p["Project_ID"] for p in merged}

    proj_path = Path(args.out_projects)
    with proj_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "Institution", "Project_ID", "Project_Name", "Country", "Status",
            "Approval_Date", "Total_Commitment_USD", "Sector_Codes", "Non_Sovereign",
        ])
        w.writeheader()
        w.writerows(merged)

    docs_path = Path(args.out_documents)
    with docs_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Institution", "Project_ID", "Country", "Doc_Title", "URL"])
        w.writeheader()
        w.writerows(d for d in all_docs if d["Project_ID"] in kept_ids)

    status_tally = defaultdict(int)
    for p in merged:
        status_tally[p["Status"]] += 1
    total_commit = sum(float(p["Total_Commitment_USD"]) for p in merged) / 1e9

    print(f"\nWrote {proj_path} ({len(merged)} projects)")
    print(f"Wrote {docs_path} ({sum(1 for d in all_docs if d['Project_ID'] in kept_ids)} document links)")
    print(f"Status breakdown: {dict(status_tally)}")
    print(f"Total commitment: ${total_commit:.2f}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
