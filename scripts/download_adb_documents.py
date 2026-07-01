#!/usr/bin/env python3
"""
Download project PDFs for the ADB housing/urban-renovation universe.

Like IDB, ADB embeds document URLs directly in its IATI activity
records; fetch_adb_housing_projects.py already wrote
outputs/universe/adb_housing_documents.csv with one row per PDF link
(Project_ID is the base project number, e.g. "37056-013", with no
underscores -- same filename-parsing pattern as the IDB downloader).

adb.org document URLs 403 Python's `requests` (same Cloudflare
fingerprint issue as IDB) but pass plain `curl` -- see
download_iadb_documents.py for the full explanation.

Usage:
  python3 download_adb_documents.py --from-csv outputs/universe/adb_housing_documents.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs-expanded"

# adb.org 403s Python's `requests` (same Cloudflare fingerprint issue as
# IDB) but passes plain `curl` -- see download_iadb_documents.py for the
# full explanation. adb.org also rate-limits bursts of requests (429),
# unlike IDB's host; curl_fetch backs off and retries on 429.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def curl_fetch(url: str, dest: Path, timeout: int = 60, retries: int = 3) -> bool:
    delay = 3.0
    for attempt in range(retries):
        result = subprocess.run(
            ["curl", "-sL", "-A", UA, "--max-time", str(timeout), "-o", str(dest), "-w", "%{http_code}", url],
            capture_output=True, text=True,
        )
        code = result.stdout.strip()
        if code == "429":
            time.sleep(delay)
            delay *= 2
            continue
        if code != "200" or not dest.exists() or dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            return False
        return dest.read_bytes()[:4] == b"%PDF"
    dest.unlink(missing_ok=True)
    return False


def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len] or "doc"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-csv", default=str(ROOT / "outputs" / "universe" / "adb_housing_documents.csv"))
    ap.add_argument("--out", default=str(DOCS_DIR))
    ap.add_argument("--limit", type=int, default=0, help="Only download the first N documents (0 = no limit)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.from_csv) as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    manifest_path = out_dir / "_manifest_adb.csv"
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
