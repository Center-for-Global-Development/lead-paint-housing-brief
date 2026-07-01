#!/usr/bin/env python3
"""
Download project PDFs for the IDB housing/urban-renovation universe.

Unlike the World Bank pipeline, IDB embeds document URLs directly in its
IATI activity records, so there is no separate documents API to query --
fetch_iadb_housing_projects.py already wrote
outputs/universe/iadb_housing_documents.csv with one row per PDF link.
This script just downloads them.

Files are named <Project_ID>_<n>_<slug-of-title>.pdf so search scripts
downstream can recover the project ID -- the leading token up to the
first "_NN_" is the full IATI identifier (which contains no
underscores itself).

Usage:
  python3 download_iadb_documents.py --from-csv outputs/universe/iadb_housing_documents.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs-expanded"

# www.iadb.org / idbdocs.iadb.org sit behind Cloudflare bot detection that
# 403s Python's `requests` (its TLS/HTTP2 fingerprint gets flagged) but
# passes plain `curl`. Shell out to curl for this host; webimages.iadb.org
# (the IATI XML host used in fetch_iadb_projects.py) has no such issue.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def curl_fetch(url: str, dest: Path, timeout: int = 60) -> bool:
    result = subprocess.run(
        ["curl", "-sL", "-A", UA, "--max-time", str(timeout), "-o", str(dest), "-w", "%{http_code}", url],
        capture_output=True, text=True,
    )
    code = result.stdout.strip()
    if code != "200" or not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        return False
    return dest.read_bytes()[:4] == b"%PDF"


def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len] or "doc"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-csv", default=str(ROOT / "outputs" / "universe" / "iadb_housing_documents.csv"))
    ap.add_argument("--out", default=str(DOCS_DIR))
    ap.add_argument("--limit", type=int, default=0, help="Only download the first N documents (0 = no limit)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.from_csv) as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    manifest_path = out_dir / "_manifest_iadb.csv"
    manifest_rows = []
    per_project_counter: dict[str, int] = {}

    n_ok, n_skip, n_fail = 0, 0, 0
    for i, row in enumerate(rows, 1):
        pid = row["Project_ID"]
        per_project_counter[pid] = per_project_counter.get(pid, 0) + 1
        n = per_project_counter[pid]
        slug = slugify(row.get("Doc_Title", "") or "doc")
        fname = f"{pid}_{n:02d}_{slug}.pdf"
        dest = out_dir / fname

        if dest.exists() and dest.stat().st_size > 0:
            n_skip += 1
            manifest_rows.append({**row, "Filename": fname})
            continue

        if curl_fetch(row["URL"], dest):
            n_ok += 1
            manifest_rows.append({**row, "Filename": fname})
            if i % 25 == 0:
                print(f"  [{i}/{len(rows)}] downloaded...", file=sys.stderr)
        else:
            print(f"  !! [{i}/{len(rows)}] {pid}: fetch failed ({row['URL']})", file=sys.stderr)
            n_fail += 1

    with manifest_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Institution", "Project_ID", "Country", "Doc_Title", "URL", "Filename"])
        w.writeheader()
        w.writerows(manifest_rows)

    print(f"\nDownloaded: {n_ok}  Already present: {n_skip}  Failed: {n_fail}")
    print(f"Wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
