# Lead paint in World Bank, IDB, and ADB housing projects

Code, data, and analysis behind a Center for Global Development piece
auditing whether World Bank, Inter-American Development Bank (IDB),
and Asian Development Bank (ADB) housing/urban-renovation projects
commit to testing for, removing, or excluding lead-based paint.
Companion to the drinking-water lead-testing audits —
[lead-testing-world-bank-brief](https://github.com/Center-for-Global-Development/lead-testing-world-bank-brief)
and [lead-testing-iadb-brief](https://github.com/Center-for-Global-Development/lead-testing-iadb-brief)
— but **integrates all three institutions into one combined analysis**,
since housing portfolios (unlike water-supply ones) are directly
comparable across banks without a region-specific mandate difference.
(African Development Bank was evaluated and excluded — see "Known
limitations".)

**Headline finding:** across 67 active housing/urban-renewal projects
at the three institutions ($9.08 billion in commitments, 32 countries),
**only two projects mention lead paint at all, and none commit to
systematic testing and removal.** One World Bank project in Armenia
screens renovation candidates for suspected lead-based paint and
excludes them from financing; one World Bank regional project in
Eastern/Southern Africa names lead-based paint as a potential
environmental hazard in an ESRS without attaching any testing or
removal commitment. Zero IDB or ADB projects in the scanned corpus
mention lead paint in any language searched.

## Why paint needs a different methodology than water

The water-testing audits look for lead in **numeric lab-result
tables** (mg/L values in a water-quality parameter table). Lead paint
doesn't show up that way — it shows up as **policy language** in
Environmental and Social Impact Assessments (ESIAs), Environmental and
Social Review Summaries (ESRSs), and technical specifications. So
instead of a parameter-table extractor, this pipeline classifies each
lead-paint mention by the commitment level implied by its surrounding
context:

| Verdict | Meaning |
|---|---|
| `testing-commitment` | Explicit commitment to test/survey/screen for lead paint before renovation or demolition |
| `removal-commitment` | Explicit commitment to remove, abate, or encapsulate lead paint if found |
| `specification-commitment` | Procurement/technical specs require lead-free paint |
| `hazard-identified` | Lead paint named as a potential hazard, with no specific commitment attached |
| `mentioned` | Keyword hit with no classifiable context |
| `absent` | No lead-paint mention in any scanned document |
| `no-docs` | No documents downloaded / scanned |

A nuance worth flagging up front: some projects screen renovation
candidates for suspected lead paint and **exclude** those properties
from financing entirely, rather than testing-then-remediating. This
pipeline currently classifies "screened out and excluded" language as
`testing-commitment` since it does involve an active screening step,
but it's a different (arguably stronger, since it avoids exposure
rather than managing it) mechanism than lab-testing individual
surfaces. Read the underlying passage before citing any
`testing-commitment` verdict — same spot-check discipline as the water
audits' `confirmed` verdict.

## Sector codes

**World Bank** (own 2/3-letter scheme, verified against the API's
sector-name facet — not guessed):
- `YYH` = Housing Construction (modern taxonomy) — **default**
- `YH` = Housing Construction (legacy taxonomy, much larger population,
  same WWC-vs-WC pattern as the water pipeline). `--include-legacy`
  widens to this.

**IDB** (OECD DAC 5-digit codes, verified against the IATI Sector
codelist):
- `16030` = Housing policy and administrative management
- `16040` = Low-cost housing — **default, together with 16030**
- `43030` / `43032` = Urban development (broader; often includes
  housing rehabilitation but isn't exclusively about housing).
  `--include-urban` widens to include these.

**ADB** (same DAC codes as IDB — `16030` + `16040` — since ADB also
publishes to IATI using the standard OECD scheme):
- **Sovereign vs. non-sovereign filtering.** ADB's housing-sector tag
  captures both government-implemented construction/upgrading programs
  (which carry ESIA-type safeguards documents) and loans to private
  housing-finance companies — pure financial-intermediary transactions
  with no construction component and therefore no possible lead-paint
  safeguards document. The default universe **excludes non-sovereign
  operations**, identified by the IATI signal `participating-org
  role="4"` (Implementing) `type="70"` (Private Sector). This mattered
  in practice: across a country sample, non-sovereign housing-finance
  loans (to companies like Shapoorji, Shubham, IIFL, Aavas) accounted
  for roughly $4B of a naive $5.8B housing-sector total — money that
  would have inflated the denominator with projects that can never
  produce a lead-paint finding. `--include-non-sovereign` keeps them
  (tagged with a `Non_Sovereign` column) for anyone who wants to
  reproduce the unfiltered number.

## Quick start

```bash
# 1. Install Python dependencies
python3 -m pip install -r requirements.txt

# 2. Install pdftotext (poppler)
brew install poppler                # macOS
# apt-get install poppler-utils     # Debian/Ubuntu

# 3. Run the full pipeline (downloads PDFs from both institutions)
make all

# Or just rebuild the audit + chart from cached intermediates:
make chart && make verify
```

`make help` lists every target.

## Folder layout

```
├── README.md
├── LICENSE                     MIT
├── CITATION.cff
├── Makefile
├── requirements.txt
├── .gitignore
│
├── docs-expanded/              PDFs from all three institutions (gitignored)
│   ├── _manifest.csv           WB download manifest
│   ├── _manifest_iadb.csv      IDB download manifest
│   └── _manifest_adb.csv       ADB download manifest
├── docs-extracted/             Plain-text extracted from every PDF (committed)
│
├── scripts/
│   ├── fetch_wb_housing_projects.py    WB housing universe (WB Projects API)
│   ├── fetch_iadb_housing_projects.py  IDB housing universe (IATI files)
│   ├── fetch_adb_housing_projects.py   ADB housing universe (IATI files, sovereign-only)
│   ├── merge_universe.py               Combine all three into one schema
│   ├── download_wb_documents.py        WB Documents (WDS) API downloader
│   ├── download_iadb_documents.py      IDB document downloader (curl-based; see IDB water repo for why)
│   ├── download_adb_documents.py       ADB document downloader (curl-based, with 429 backoff)
│   ├── extract_text.py                 pdftotext wrapper (shared logic across all sibling pipelines)
│   ├── search_pdfs_for_lead_paint.py   Multilingual keyword search + context classification
│   ├── summarize_portfolio.py          Per-project verdict
│   ├── enrich_audit.py                 Add world-region metadata (local lookup)
│   ├── plot_by_region.py               Render the by-region, by-institution chart
│   └── verify_pipeline.py              Sanity-check headline numbers
│
└── outputs/
    ├── universe/                Project lists (WB, IDB, ADB, and merged)
    ├── search/                  Lead-paint keyword search results + classifications
    └── audit/                   Per-project verdicts + region/institution chart
```

## How the pipeline works

| Step | Script | Purpose |
|---|---|---|
| 1. universe | `fetch_wb_housing_projects.py`, `fetch_iadb_housing_projects.py`, `fetch_adb_housing_projects.py`, `merge_universe.py` | Build each institution's housing-project universe, merge into one schema with an `Institution` column. |
| 2. download | `download_wb_documents.py`, `download_iadb_documents.py`, `download_adb_documents.py` | Download project documents from each institution's own source (WB Documents API; IDB and ADB IATI-embedded links, both requiring a `curl` workaround for Cloudflare bot detection). |
| 3. extract-text | `extract_text.py` | Run `pdftotext -layout` on every PDF. |
| 4. search | `search_pdfs_for_lead_paint.py` | Multilingual (EN/ES/PT/FR) keyword search for lead-paint mentions, each classified by commitment level from surrounding context. |
| 5. audit | `summarize_portfolio.py` | Join into a per-project verdict. |
| 6. enrich | `enrich_audit.py` | Add world-region metadata (local country lookup, no API). |
| 7. chart | `plot_by_region.py` | Stacked horizontal bar chart of $ commitments by region and institution, CGD brand colours. |

## Known limitations

1. **AfDB is not included.** The African Development Bank publishes to
   IATI (57 country files) with real embedded PDF document links, but
   every AfDB document host (`afdb.org`, `evrd.afdb.org`,
   `mapafrica.afdb.org`) sits behind Cloudflare's **interactive JS
   challenge (Turnstile)**, confirmed by inspecting response headers
   (`cf-mitigated: challenge`). This is a materially harder wall than
   IDB's or ADB's bot-fingerprint blocks (which plain `curl` passes):
   Turnstile requires executing JavaScript in a real browser to solve a
   challenge, and blocks both `curl` and Python `requests` regardless
   of headers or user-agent. The alternative
   `projectsportal.afdb.org` no longer resolves. Without a working
   browser-automation path (out of scope for this pipeline), AfDB's
   safeguards documents cannot be read, so no lead-paint verdict is
   possible for its portfolio. If this changes, `fetch_afdb_housing_projects.py`
   would follow the same pattern as the IDB/ADB fetchers — the IATI
   feed itself is fine.
2. **Absence of evidence isn't strong evidence of absence.** Zero IDB
   or ADB projects in the scanned corpus mention lead paint. Download
   success rates were 89% (IDB, 419/469 within the housing corpus) and
   91% (ADB, 112/123) — most of the shortfall is dead links in the
   source IATI data, not systematic bias, but a real minority of
   documents were never read. Combined with multilingual-but-not-
   exhaustive keyword coverage (limitation 3), a true zero should be
   read as "no confirmed mention" rather than "certainly never
   discussed anywhere in these projects' full documentation."
3. **Language coverage is not exhaustive.** Lead-paint phrases are
   matched in English, Spanish, Portuguese, and French — the languages
   expected across the WB, IDB, and ADB housing portfolios in scope —
   but a professional translator would catch idioms this pipeline
   misses.
4. **Context-window classification is heuristic.** The
   testing/removal/specification classifiers look for cue words within
   ~80 characters of the lead-paint phrase. A commitment stated in a
   different sentence structure, or with more distance between cue and
   phrase, may be under-classified as `hazard-identified` or
   `mentioned` rather than the tier it actually belongs to. Any
   `testing-commitment`, `removal-commitment`, or
   `specification-commitment` verdict should be manually read before
   citing. In the current run this affects both non-`absent` verdicts:
   read `outputs/search/lead_paint_search.txt` for the P508310 (Armenia)
   and P178986 (Africa regional) passages before citing either.
5. **"Screened and excluded" vs. "tested and remediated" are conflated**
   under `testing-commitment` — see the note in "Why paint needs a
   different methodology than water" above. The one `testing-commitment`
   finding in this run (Armenia) is actually a screen-and-exclude
   mechanism, not lab testing of individual surfaces.
6. **Sector-code scope choices.** All three institutions' defaults
   exclude broader urban-development codes that often include housing
   rehabilitation as a component. `--include-legacy` (WB),
   `--include-urban` (IDB), and `--include-non-sovereign` (ADB) widen
   the universe; not run by default to keep the strictest defensible
   filter as the headline.
7. **ADB's IATI document-link data has quality issues.** Roughly 47% of
   ADB's raw `document-link` entries for the housing universe either
   point to project landing pages mislabeled as `format="application/pdf"`,
   or concatenate two URLs with no separator. `fetch_adb_housing_projects.py`
   sanitizes these (`sanitize_adb_doc_url()`) before writing the
   documents CSV; the remaining ~9% failure rate on cleaned URLs is
   genuine dead links (some reference `/project-document/` singular
   instead of `/project-documents/` plural — a typo in ADB's own data).

## Data provenance

- **World Bank project metadata:** <https://search.worldbank.org/api/v3/projects>
- **World Bank documents:** <https://search.worldbank.org/api/v3/wds>
- **IDB project + document metadata:** IDB IATI activity files,
  `https://webimages.iadb.org/iati/iadb-<Country>.xml`
- **ADB project + document metadata:** ADB IATI activity files,
  `https://www.adb.org/iati/iati-activities-<cc>.xml`

## Status

Full pipeline run complete across all three institutions. 67 projects
($9.08B, 32 countries): 14 World Bank, 26 IDB, 27 ADB (sovereign-only).
652 documents text-extracted; multilingual search run across the full
corpus; `make verify` passes. See the headline finding above.

## Citation

If you use this code or data, please cite the accompanying CGD piece
(once published) and this repository (see `CITATION.cff`).

## License

MIT (see `LICENSE`).
