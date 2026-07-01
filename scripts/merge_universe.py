#!/usr/bin/env python3
"""
Merge the World Bank, IDB, and ADB housing-project universes into one
combined CSV with a shared schema, so downstream search/audit/chart
scripts can treat all three institutions uniformly.

Inputs
------
    outputs/universe/wb_housing_projects.csv    (fetch_wb_housing_projects.py)
    outputs/universe/iadb_housing_projects.csv  (fetch_iadb_housing_projects.py)
    outputs/universe/adb_housing_projects.csv   (fetch_adb_housing_projects.py)

Output
------
    outputs/universe/combined_housing_projects.csv

All three institution-specific fetch scripts already write to a shared
column schema (Institution, Project_ID, Project_Name, Country, Status,
Approval_Date, Total_Commitment_USD, Sector_Codes), so this script is a
straight concatenation plus a project-ID-collision check. WB IDs are
"P######", IDB IDs are "XI-IATI-IADB-...", ADB IDs are bare
"NNNNN-NNN" tranche numbers -- no collision expected in practice, but
checked anyway.

AfDB is deliberately not included: its IATI feed exists, but every
AfDB document host sits behind Cloudflare's interactive JS challenge
(Turnstile), which blocks both `curl` and Python `requests` -- there is
no automatable way to download its safeguards documents with the tools
available to this pipeline. See README.md "Known limitations".
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "universe"

FIELDNAMES = ["Institution", "Project_ID", "Project_Name", "Country", "Status",
              "Approval_Date", "Total_Commitment_USD", "Sector_Codes"]


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  ! {path} not found, skipping")
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wb", default=str(OUT_DIR / "wb_housing_projects.csv"))
    ap.add_argument("--iadb", default=str(OUT_DIR / "iadb_housing_projects.csv"))
    ap.add_argument("--adb", default=str(OUT_DIR / "adb_housing_projects.csv"))
    ap.add_argument("--out", default=str(OUT_DIR / "combined_housing_projects.csv"))
    args = ap.parse_args()

    wb_rows = load_rows(Path(args.wb))
    iadb_rows = load_rows(Path(args.iadb))
    adb_rows = load_rows(Path(args.adb))

    all_rows = wb_rows + iadb_rows + adb_rows
    ids = [r["Project_ID"] for r in all_rows]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        print(f"  ! WARNING: duplicate Project_IDs across institutions: {dupes}")

    all_rows.sort(key=lambda r: float(r.get("Total_Commitment_USD") or 0), reverse=True)

    out_path = Path(args.out)
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})

    n_wb = sum(1 for r in all_rows if r["Institution"] == "World Bank")
    n_iadb = sum(1 for r in all_rows if r["Institution"] == "IDB")
    n_adb = sum(1 for r in all_rows if r["Institution"] == "ADB")
    total = sum(float(r.get("Total_Commitment_USD") or 0) for r in all_rows) / 1e9

    print(f"Wrote {out_path}")
    print(f"  World Bank: {n_wb} projects")
    print(f"  IDB:        {n_iadb} projects")
    print(f"  ADB:        {n_adb} projects")
    print(f"  Combined:   {len(all_rows)} projects, ${total:.2f}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
