#!/usr/bin/env python3
"""
Sanity-check the combined WB + IDB lead-paint pipeline's headline
numbers, mirroring the water-testing pipelines' verify_pipeline.py.

Expected ranges are loose (not exact equality) because both
portfolios shift over time. Update EXPECTED when the underlying
portfolio shifts materially.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Loose ranges as of July 2026: WB housing (YYH, strict) ~14 projects/
# $2.1B; IDB housing (16030+16040) ~26 projects/$3.0B; ADB housing
# (16030+16040, sovereign only) ~27 projects/$4.0B; combined ~67
# projects/$9.1B. AfDB is deliberately excluded (see README).
EXPECTED = {
    "min_projects": 45,
    "max_projects": 90,
    "min_commitment_usd": 6_000_000_000,
    "max_commitment_usd": 13_000_000_000,
    "min_wb_projects": 5,
    "min_iadb_projects": 10,
    "min_adb_projects": 10,
    "min_countries": 15,
    "max_countries": 40,
    "expected_verdicts": {
        "testing-commitment", "removal-commitment", "specification-commitment",
        "hazard-identified", "mentioned", "absent", "no-docs",
    },
}


def fail(msg: str):
    print(f"  ✗ FAIL: {msg}", file=sys.stderr)
    return False


def ok(msg: str):
    print(f"  ✓ {msg}")
    return True


def main() -> int:
    audit_path = ROOT / "outputs" / "audit" / "portfolio_audit.csv"
    region_path = ROOT / "outputs" / "audit" / "portfolio_audit_with_region.csv"

    if not audit_path.exists():
        return fail(f"{audit_path} not found — run `make audit` first")
    if not region_path.exists():
        return fail(f"{region_path} not found — run `make enrich` first")

    rows = list(csv.DictReader(audit_path.open()))
    region_rows = list(csv.DictReader(region_path.open()))
    passed = True

    print("Pipeline verification (WB + IDB + ADB lead paint)")
    print("=" * 50)

    n = len(rows)
    if EXPECTED["min_projects"] <= n <= EXPECTED["max_projects"]:
        passed &= ok(f"Project count: {n} (expected {EXPECTED['min_projects']}-{EXPECTED['max_projects']})")
    else:
        passed &= fail(f"Project count: {n} (expected {EXPECTED['min_projects']}-{EXPECTED['max_projects']})")

    total = sum(float(r["commitment_usd"]) for r in rows)
    if EXPECTED["min_commitment_usd"] <= total <= EXPECTED["max_commitment_usd"]:
        passed &= ok(f"Total commitment: ${total/1e9:.2f}B")
    else:
        passed &= fail(f"Total commitment: ${total/1e9:.2f}B (out of expected range)")

    n_wb = sum(1 for r in rows if r["institution"] == "World Bank")
    n_iadb = sum(1 for r in rows if r["institution"] == "IDB")
    n_adb = sum(1 for r in rows if r["institution"] == "ADB")
    if n_wb >= EXPECTED["min_wb_projects"]:
        passed &= ok(f"World Bank projects: {n_wb}")
    else:
        passed &= fail(f"World Bank projects: {n_wb} (expected >= {EXPECTED['min_wb_projects']})")
    if n_iadb >= EXPECTED["min_iadb_projects"]:
        passed &= ok(f"IDB projects: {n_iadb}")
    else:
        passed &= fail(f"IDB projects: {n_iadb} (expected >= {EXPECTED['min_iadb_projects']})")
    if n_adb >= EXPECTED["min_adb_projects"]:
        passed &= ok(f"ADB projects: {n_adb}")
    else:
        passed &= fail(f"ADB projects: {n_adb} (expected >= {EXPECTED['min_adb_projects']})")

    found_verdicts = {r["verdict"] for r in rows}
    extras = found_verdicts - EXPECTED["expected_verdicts"]
    if extras:
        passed &= fail(f"Unknown verdict(s) emitted: {sorted(extras)}")
    else:
        passed &= ok(f"Verdict vocabulary OK ({len(found_verdicts)} of {len(EXPECTED['expected_verdicts'])} used)")

    countries = {r["country"] for r in rows if r["country"]}
    if EXPECTED["min_countries"] <= len(countries) <= EXPECTED["max_countries"]:
        passed &= ok(f"Countries: {len(countries)}")
    else:
        passed &= fail(f"Countries: {len(countries)} (out of expected range)")

    regions = {r["region"] for r in region_rows if r.get("region")}
    if "Unknown" in regions:
        passed &= fail("Region 'Unknown' present in enriched audit — region lookup needs updating")
    else:
        passed &= ok(f"All projects have a known region ({len(regions)} regions)")

    print("=" * 50)
    if passed:
        print("All checks passed.")
        return 0
    else:
        print("Some checks failed. See above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
