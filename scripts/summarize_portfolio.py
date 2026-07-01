#!/usr/bin/env python3
"""
Portfolio-wide summariser for the combined WB + IDB + ADB lead-in-paint
audit.

Takes the outputs of:
  - merge_universe.py           -> combined_housing_projects.csv
  - search_pdfs_for_lead_paint.py -> lead_paint_search.csv
  - download_wb_documents.py / download_iadb_documents.py /
    download_adb_documents.py -> manifests

and emits:
  - portfolio_audit.csv  -- one row per project with the audit verdict
  - portfolio_audit.md   -- readable summary with top-line stats

Verdict taxonomy (different from the water-testing audits, since lead
paint shows up as policy language, not lab-result tables):
  "testing-commitment"       -- explicit commitment to test/survey for
                                 lead paint before renovation/demolition
  "removal-commitment"       -- explicit commitment to remove/abate/
                                 encapsulate lead paint if found
  "specification-commitment" -- procurement/technical specs require
                                 lead-free paint
  "hazard-identified"        -- lead paint named as a potential hazard,
                                 no specific commitment attached
  "mentioned"                -- keyword hit with no classifiable context
  "absent"                   -- no lead-paint mention in any scanned doc
  "no-docs"                  -- no documents downloaded / scanned

Usage:
    python3 summarize_portfolio.py
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--projects", default=str(root / "outputs/universe/combined_housing_projects.csv"))
    ap.add_argument("--search", default=str(root / "outputs/search/lead_paint_search.csv"))
    ap.add_argument("--out-csv", default=str(root / "outputs/audit/portfolio_audit.csv"))
    ap.add_argument("--out-md", default=str(root / "outputs/audit/portfolio_audit.md"))
    args = ap.parse_args()

    projects = load_csv(Path(args.projects))
    search = load_csv(Path(args.search))
    search_by_pid = {row["Project_ID"]: row for row in search}

    VERDICT_MAP = {
        "testing": "testing-commitment",
        "removal": "removal-commitment",
        "specification": "specification-commitment",
        "hazard": "hazard-identified",
    }

    audit_rows = []
    totals = defaultdict(int)

    for p in projects:
        pid = p["Project_ID"]
        institution = p["Institution"]
        country = p["Country"]
        name = p["Project_Name"]
        commitment = int(float(p.get("Total_Commitment_USD") or 0))

        s = search_by_pid.get(pid)
        if s is None:
            verdict = "no-docs"
            n_docs = 0
            total_hits = 0
            classes_found = ""
        else:
            n_docs = int(s.get("N_Documents") or 0)
            total_hits = int(s.get("Total_Hits") or 0)
            classes_found = s.get("Classifications_Found") or ""
            best = s.get("Best_Classification") or ""
            if n_docs == 0:
                verdict = "no-docs"
            elif best:
                verdict = VERDICT_MAP.get(best, "mentioned")
            elif total_hits > 0:
                verdict = "mentioned"
            else:
                verdict = "absent"

        totals[verdict] += 1
        totals["_usd"] += commitment

        audit_rows.append({
            "project_id": pid,
            "institution": institution,
            "country": country,
            "project_name": name,
            "commitment_usd": commitment,
            "n_docs_scanned": n_docs,
            "lead_paint_hits": total_hits,
            "classifications_found": classes_found,
            "verdict": verdict,
        })

    audit_rows.sort(key=lambda r: r["commitment_usd"], reverse=True)

    out_csv = Path(args.out_csv)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()) if audit_rows else [])
        w.writeheader()
        w.writerows(audit_rows)

    out_md = Path(args.out_md)
    with out_md.open("w") as f:
        f.write("# Portfolio Audit — Lead Paint in WB + IDB Housing Projects\n\n")
        f.write(f"Total projects: **{len(audit_rows)}**   |   ")
        f.write(f"Total commitment: **${totals['_usd']/1e9:,.2f} B**\n\n")
        n_wb = sum(1 for r in audit_rows if r["institution"] == "World Bank")
        n_iadb = sum(1 for r in audit_rows if r["institution"] == "IDB")
        n_adb = sum(1 for r in audit_rows if r["institution"] == "ADB")
        f.write(f"World Bank: {n_wb} projects   |   IDB: {n_iadb} projects   |   ADB: {n_adb} projects\n\n")
        f.write("## Verdict distribution\n\n")
        f.write("| Verdict | N projects | $B |\n|---|---:|---:|\n")
        usd_by_verdict = defaultdict(int)
        n_by_verdict = defaultdict(int)
        for r in audit_rows:
            usd_by_verdict[r["verdict"]] += r["commitment_usd"]
            n_by_verdict[r["verdict"]] += 1
        for v in ["testing-commitment", "removal-commitment", "specification-commitment",
                  "hazard-identified", "mentioned", "absent", "no-docs"]:
            n = n_by_verdict.get(v, 0)
            if n:
                f.write(f"| {v} | {n} | {usd_by_verdict[v]/1e9:,.2f} |\n")

        f.write("\n## Per-project details (sorted by commitment)\n\n")
        f.write("| Project | Institution | Country | $M | Docs | Hits | Classes | Verdict |\n")
        f.write("|---|---|---|---:|---:|---:|---|---|\n")
        for r in audit_rows:
            f.write(f"| {r['project_id']} | {r['institution']} | {r['country']} | "
                    f"{r['commitment_usd']/1e6:,.0f} | "
                    f"{r['n_docs_scanned']} | "
                    f"{r['lead_paint_hits']} | "
                    f"{r['classifications_found'] or '—'} | "
                    f"**{r['verdict']}** |\n")

    print(f"Wrote {out_csv}")
    print(f"Wrote {out_md}")
    print(f"\nTotals: {dict((k, v) for k, v in totals.items() if not k.startswith('_'))}")
    print(f"Total commitment: ${totals['_usd']/1e9:,.2f} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
