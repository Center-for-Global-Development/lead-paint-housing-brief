#!/usr/bin/env python3
"""
Search World Bank + IDB + ADB housing/urban-renovation project PDFs
for mentions of lead paint, and classify what kind of commitment (if
any) each mention represents.

Unlike the water-testing audits (which look for numeric parameter-table
rows), lead paint doesn't show up in lab-result tables — it shows up as
policy language in ESIAs/ESMPs and technical specifications. So instead
of a table-extraction step, this script classifies each keyword hit by
scanning its surrounding context for one of four commitment levels:

  testing       -- explicit commitment to test/survey/inspect for lead
                   paint before renovation or demolition
  removal       -- explicit commitment to remove, abate, or encapsulate
                   lead paint if found
  specification -- procurement/technical specs require lead-free paint
                   for new construction or renovation
  hazard        -- lead paint named as a potential hazard (e.g. in
                   older buildings) without a specific testing/removal/
                   specification commitment
  (none of the above -> "mentioned", handled downstream in
  summarize_portfolio.py)

Multilingual: English, Spanish, Portuguese, and French (the World Bank
corpus spans Latin America, Brazil, and Francophone Africa housing
projects; unlike "lead" the metal, "peinture au plomb" has no
verb-homonym problem in any of these languages, so all four are
matched directly rather than needing English's context-gating).

Expects docs-expanded/ to contain PDFs named either:
    P######_Country_Type.pdf                      (World Bank)
    XI-IATI-IADB-XX-LNNNN_NN_slug.pdf              (IDB)
    NNNNN-NNN_NN_slug.pdf                          (ADB)

Usage:
    python3 search_pdfs_for_lead_paint.py
    python3 search_pdfs_for_lead_paint.py --show-snippets
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs-expanded"
OUT_DIR = ROOT / "outputs" / "search"
EXTRACTED_DIR = ROOT / "docs-extracted"
UNIVERSE_CSV = ROOT / "outputs" / "universe" / "combined_housing_projects.csv"

CONTEXT_WINDOW = 150

# ---------------------------------------------------------------------------
# Lead-paint mention patterns, EN/ES/PT/FR. "Lead paint" phrases are
# multi-word and unambiguous in every language here, so no verb-homonym
# gating is needed (contrast with the water pipelines' bare "lead"/"Pb").
# ---------------------------------------------------------------------------
LEAD_PAINT_PATTERNS = {
    "en": [
        r"\blead[- ]based\s+paint\b",
        r"\blead\s+paint\b",
        r"\bleaded\s+paint\b",
        r"\bpaint\s+containing\s+lead\b",
        r"\blead\s+in\s+paint\b",
        r"\blead[- ]free\s+paint\b",
    ],
    "es": [
        r"\bpintura\s+(?:a\s+base\s+de\s+plomo|con\s+plomo|con\s+contenido\s+de\s+plomo|plomada)\b",
        r"\bplomo\s+en\s+(?:la\s+)?pintura\b",
        r"\bpintura\s+(?:libre|sin)\s+de?\s*plomo\b",
    ],
    "pt": [
        r"\btinta\s+(?:à\s+base\s+de\s+chumbo|com\s+chumbo|contendo\s+chumbo)\b",
        r"\bchumbo\s+n[ao]\s+tinta\b",
        r"\btinta\s+livre\s+de\s+chumbo\b",
        r"\btinta\s+sem\s+chumbo\b",
    ],
    "fr": [
        r"\bpeinture\s+(?:au\s+plomb|contenant\s+du\s+plomb|à\s+base\s+de\s+plomb)\b",
        r"\bplomb\s+dans\s+la\s+peinture\b",
        r"\bpeinture\s+sans\s+plomb\b",
    ],
}
LEAD_PAINT_RE = {
    lang: re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    for lang, patterns in LEAD_PAINT_PATTERNS.items()
}

# ---------------------------------------------------------------------------
# Classification cues, applied to a window of text around each hit.
# Order matters: testing/removal/specification are checked before the
# generic "hazard" fallback.
# ---------------------------------------------------------------------------
CLASSIFIERS = [
    ("testing", re.compile(
        r"\b(?:test(?:ing)?|survey(?:ed)?|inspect(?:ion)?|screen(?:ing)?|sampl(?:e|ing)|assess(?:ment)?)\b.{0,80}\blead[- ]?(?:based\s+)?paint\b|"
        r"\blead[- ]?(?:based\s+)?paint\b.{0,80}\b(?:test(?:ing)?|survey(?:ed)?|inspect(?:ion)?|screen(?:ing)?|sampl(?:e|ing)|assess(?:ment)?)\b|"
        r"\b(?:prueba|inspecci[óo]n|muestreo|evaluaci[óo]n)\b.{0,80}\bpintura.{0,20}plomo\b|"
        r"\bpintura.{0,20}plomo\b.{0,80}\b(?:prueba|inspecci[óo]n|muestreo|evaluaci[óo]n)\b|"
        r"\b(?:teste|inspe[çc][ãa]o|amostragem|avalia[çc][ãa]o)\b.{0,80}\btinta.{0,20}chumbo\b|"
        r"\btinta.{0,20}chumbo\b.{0,80}\b(?:teste|inspe[çc][ãa]o|amostragem|avalia[çc][ãa]o)\b|"
        r"\b(?:test|inspection|d[ée]pistage|[ée]chantillonnage)\b.{0,80}\bpeinture.{0,20}plomb\b|"
        r"\bpeinture.{0,20}plomb\b.{0,80}\b(?:test|inspection|d[ée]pistage|[ée]chantillonnage)\b",
        re.IGNORECASE | re.DOTALL)),
    ("removal", re.compile(
        r"\b(?:remov(?:e|al)|abate(?:ment)?|encapsulat(?:e|ion)|strip(?:ping)?|remediat(?:e|ion))\b.{0,80}\blead[- ]?(?:based\s+)?paint\b|"
        r"\blead[- ]?(?:based\s+)?paint\b.{0,80}\b(?:remov(?:e|al)|abate(?:ment)?|encapsulat(?:e|ion)|strip(?:ping)?|remediat(?:e|ion))\b|"
        r"\b(?:remoci[óo]n|eliminaci[óo]n|encapsulaci[óo]n|retiro)\b.{0,80}\bpintura.{0,20}plomo\b|"
        r"\bpintura.{0,20}plomo\b.{0,80}\b(?:remoci[óo]n|eliminaci[óo]n|encapsulaci[óo]n|retiro)\b|"
        r"\b(?:remo[çc][ãa]o|elimina[çc][ãa]o|encapsulamento)\b.{0,80}\btinta.{0,20}chumbo\b|"
        r"\btinta.{0,20}chumbo\b.{0,80}\b(?:remo[çc][ãa]o|elimina[çc][ãa]o|encapsulamento)\b|"
        r"\b(?:enl[èe]vement|[ée]limination|encapsulation)\b.{0,80}\bpeinture.{0,20}plomb\b|"
        r"\bpeinture.{0,20}plomb\b.{0,80}\b(?:enl[èe]vement|[ée]limination|encapsulation)\b",
        re.IGNORECASE | re.DOTALL)),
    ("specification", re.compile(
        r"\b(?:shall|must|require[sd]?|prohibit(?:ed|ion)?|ban(?:ned)?|specification)\b.{0,80}\blead[- ]?(?:based\s+|free\s+)?paint\b|"
        r"\blead[- ]?(?:based\s+|free\s+)?paint\b.{0,80}\b(?:shall|must|require[sd]?|prohibit(?:ed|ion)?|ban(?:ned)?|specification)\b|"
        r"\b(?:deber[áa]|requiere|prohibici[óo]n|proh[íi]be|especificaci[óo]n)\b.{0,80}\bpintura.{0,30}plomo\b|"
        r"\bpintura.{0,30}plomo\b.{0,80}\b(?:deber[áa]|requiere|prohibici[óo]n|proh[íi]be|especificaci[óo]n)\b|"
        r"\b(?:dever[áa]|exige|proibi[çc][ãa]o|pro[íi]be|especifica[çc][ãa]o)\b.{0,80}\btinta.{0,30}chumbo\b|"
        r"\btinta.{0,30}chumbo\b.{0,80}\b(?:dever[áa]|exige|proibi[çc][ãa]o|pro[íi]be|especifica[çc][ãa]o)\b|"
        r"\b(?:doit|exige|interdiction|interdit|sp[ée]cification)\b.{0,80}\bpeinture.{0,30}plomb\b|"
        r"\bpeinture.{0,30}plomb\b.{0,80}\b(?:doit|exige|interdiction|interdit|sp[ée]cification)\b",
        re.IGNORECASE | re.DOTALL)),
]


def load_project_names() -> dict[str, tuple[str, str, str]]:
    """Project_ID -> (Institution, Country, short project name)."""
    names = {}
    if not UNIVERSE_CSV.exists():
        return names
    with UNIVERSE_CSV.open() as f:
        for row in csv.DictReader(f):
            names[row["Project_ID"]] = (row["Institution"], row["Country"], row["Project_Name"][:40])
    return names


PROJECT_NAMES = load_project_names()


def extract_text(pdf_path: Path) -> str:
    txt_path = EXTRACTED_DIR / (pdf_path.stem + ".txt")
    if txt_path.exists():
        try:
            return txt_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"  !! reading {txt_path} failed: {e}", file=sys.stderr)
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", "-nopgbrk", str(pdf_path), "-"],
            check=True, capture_output=True, timeout=300,
        )
        return out.stdout.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        print(f"  !! pdftotext failed on {pdf_path.name}: {e}", file=sys.stderr)
        return ""
    except subprocess.TimeoutExpired:
        print(f"  !! pdftotext timed out on {pdf_path.name}", file=sys.stderr)
        return ""


def project_id_from_filename(name: str) -> str | None:
    # World Bank: leading P###### token.
    m = re.match(r"(P\d{6})", name)
    if m:
        return m.group(1)
    # IDB: "<IATI_ID>_<NN>_<slug>.pdf" -- IATI ID has no underscores itself.
    m = re.match(r"^(.+?)_\d{2}_", name)
    return m.group(1) if m else None


def snippet(text: str, start: int, end: int, window: int = CONTEXT_WINDOW) -> str:
    a = max(0, start - window)
    b = min(len(text), end + window)
    s = text[a:b].replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def classify_hit(text: str, start: int, end: int, window: int = 200) -> str:
    """Classify a single lead-paint mention using nearby context."""
    a = max(0, start - window)
    b = min(len(text), end + window)
    ctx = text[a:b]
    for label, rx in CLASSIFIERS:
        if rx.search(ctx):
            return label
    return "hazard"


def analyse_document(text: str) -> dict:
    hits = []
    for lang, rx in LEAD_PAINT_RE.items():
        for m in rx.finditer(text):
            cls = classify_hit(text, m.start(), m.end())
            hits.append({
                "lang": lang, "match": m.group(0), "start": m.start(), "end": m.end(),
                "classification": cls,
            })
    return {"hits": hits}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", default=str(DOCS_DIR))
    ap.add_argument("--out-csv", default=str(OUT_DIR / "lead_paint_search.csv"))
    ap.add_argument("--out-report", default=str(OUT_DIR / "lead_paint_search.txt"))
    ap.add_argument("--show-snippets", action="store_true")
    args = ap.parse_args()

    docs_dir = Path(args.docs)
    pdfs = sorted(docs_dir.glob("*.pdf")) if docs_dir.is_dir() else []
    if not pdfs and EXTRACTED_DIR.is_dir():
        pdfs = sorted(docs_dir / (t.stem + ".pdf") for t in EXTRACTED_DIR.glob("*.txt"))
        print(f"No PDFs found in {docs_dir}; using {len(pdfs)} extracted text files from {EXTRACTED_DIR}", file=sys.stderr)
    if not pdfs:
        print(f"No PDFs or extracted text found (checked {docs_dir} and {EXTRACTED_DIR})", file=sys.stderr)
        return 2

    per_project: dict[str, list[tuple[str, dict | None]]] = defaultdict(list)

    for pdf in pdfs:
        pid = project_id_from_filename(pdf.name) or "UNKNOWN"
        print(f"[{pid}] {pdf.name}", file=sys.stderr)
        text = extract_text(pdf)
        if not text:
            per_project[pid].append((pdf.name, None))
            continue
        result = analyse_document(text)
        per_project[pid].append((pdf.name, {**result, "text": text}))
        if args.show_snippets and result["hits"]:
            for h in result["hits"]:
                print(f"    ⤷ [{h['lang']}/{h['classification']}] '{h['match']}': …{snippet(text, h['start'], h['end'])}…")

    csv_path = Path(args.out_csv)
    report_path = Path(args.out_report)

    with csv_path.open("w", newline="") as f, report_path.open("w") as rep:
        w = csv.writer(f)
        w.writerow(["Project_ID", "Institution", "Country", "Short_Name", "N_Documents",
                    "Total_Hits", "Best_Classification", "Classifications_Found"])

        rep.write("LEAD-PAINT SEARCH — per-project evidence report (WB + IDB + ADB housing)\n")
        rep.write("=" * 70 + "\n\n")

        # Priority order for "best" classification per project (most
        # concrete commitment wins for the headline verdict).
        priority = {"testing": 4, "removal": 3, "specification": 2, "hazard": 1}

        for pid in sorted(per_project):
            institution, country, short = PROJECT_NAMES.get(pid, ("?", "?", "?"))
            docs = per_project[pid]
            total_hits = 0
            classes_found: set[str] = set()
            for name, res in docs:
                if res is None:
                    continue
                total_hits += len(res["hits"])
                classes_found.update(h["classification"] for h in res["hits"])

            best = max(classes_found, key=lambda c: priority.get(c, 0)) if classes_found else ""

            w.writerow([pid, institution, country, short, len(docs), total_hits,
                        best, ", ".join(sorted(classes_found))])

            rep.write(f"{pid}  [{institution}]  {country} — {short}\n")
            rep.write(f"  Documents scanned: {len(docs)}\n")
            rep.write(f"  Lead-paint mentions: {total_hits}\n")
            rep.write(f"  Classifications found: {', '.join(sorted(classes_found)) or '(none)'}\n")
            for name, res in docs:
                if res is None:
                    rep.write(f"    - {name}: [extraction failed]\n")
                    continue
                if not res["hits"]:
                    continue
                rep.write(f"    - {name}: {len(res['hits'])} hit(s)\n")
                for h in res["hits"]:
                    rep.write(f"        • [{h['lang']}/{h['classification']}] '{h['match']}' … {snippet(res['text'], h['start'], h['end'])} …\n")
            rep.write("\n")

    print(f"\nWrote {csv_path}\nWrote {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
