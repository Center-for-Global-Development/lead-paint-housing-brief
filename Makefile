# Makefile for the lead-paint-housing-brief analysis pipeline.
#
# Companion to lead-testing-world-bank-brief and lead-testing-iadb-brief
# (drinking-water lead testing) -- this pipeline audits World Bank,
# IDB, and ADB housing/urban-renovation projects for lead-in-paint
# commitments, combining all three institutions into one analysis.
#
# AfDB is deliberately excluded: its document hosts sit behind
# Cloudflare's interactive JS challenge, which blocks both curl and
# Python requests. See README.md "Known limitations".
#
# Usage:
#     make help               # show targets
#     make audit              # build the per-project audit (fast)
#     make chart              # also build the by-region chart
#     make all                # full rebuild from scratch (downloads PDFs)
#     make clean              # remove generated outputs (keeps PDFs + cache)
#     make distclean          # also remove docs-expanded/ and IATI caches

PY        := python3
SCRIPTS   := scripts
OUT       := outputs
DOCS      := docs-expanded

# ----- Outputs --------------------------------------------------------
WB_UNIVERSE     := $(OUT)/universe/wb_housing_projects.csv
IADB_UNIVERSE   := $(OUT)/universe/iadb_housing_projects.csv
IADB_DOCUMENTS  := $(OUT)/universe/iadb_housing_documents.csv
ADB_UNIVERSE    := $(OUT)/universe/adb_housing_projects.csv
ADB_DOCUMENTS   := $(OUT)/universe/adb_housing_documents.csv
COMBINED        := $(OUT)/universe/combined_housing_projects.csv
LAW_STATUS      := $(OUT)/reference/who_lead_paint_law_status.csv
SEARCH          := $(OUT)/search/lead_paint_search.csv
AUDIT           := $(OUT)/audit/portfolio_audit.csv
AUDIT_REG       := $(OUT)/audit/portfolio_audit_with_region.csv
CHART           := $(OUT)/audit/projects_by_region.png
RISK_MAP        := $(OUT)/audit/lead_paint_risk_map.png
RISK_BARS       := $(OUT)/audit/lead_paint_risk_bars.png
MARKET_SURVEYS  := $(OUT)/reference/paint_market_surveys.csv
MANIFEST        := $(DOCS)/_manifest.csv

.PHONY: help all clean distclean audit chart risk-map risk-bars verify \
        universe download extract-text search enrich

help:
	@echo "Targets:"
	@echo "  universe   Build WB + IDB + ADB housing-project universes and merge them"
	@echo "  download   Download project PDFs for all three institutions (slow)"
	@echo "  extract-text  Run pdftotext on each PDF into docs-extracted/"
	@echo "  search     Run multilingual lead-paint keyword search + classification"
	@echo "  audit      Build portfolio_audit.csv (fast)"
	@echo "  enrich     Add world-region metadata to the audit"
	@echo "  chart      Render the by-region chart"
	@echo "  risk-map   Render the lead-paint risk world map (law status + market surveys)"
	@echo "  risk-bars  Render the lead-paint risk bar chart (same data, sorted table-like view)"
	@echo "  verify     Sanity-check the audit outputs against expected ranges"
	@echo "  all        Full rebuild (downloads + reprocesses)"
	@echo "  clean      Remove generated outputs (keeps downloaded PDFs)"
	@echo "  distclean  Also remove docs-expanded/ and the IATI caches"

# ----- Step targets ---------------------------------------------------

universe: $(COMBINED)
$(WB_UNIVERSE):
	$(PY) $(SCRIPTS)/fetch_wb_housing_projects.py
$(IADB_UNIVERSE) $(IADB_DOCUMENTS):
	$(PY) $(SCRIPTS)/fetch_iadb_housing_projects.py
$(ADB_UNIVERSE) $(ADB_DOCUMENTS):
	$(PY) $(SCRIPTS)/fetch_adb_housing_projects.py
$(COMBINED): $(WB_UNIVERSE) $(IADB_UNIVERSE) $(ADB_UNIVERSE)
	$(PY) $(SCRIPTS)/merge_universe.py

download: $(MANIFEST)
$(MANIFEST): $(WB_UNIVERSE) $(IADB_DOCUMENTS) $(ADB_DOCUMENTS)
	$(PY) $(SCRIPTS)/download_wb_documents.py --from-csv $(WB_UNIVERSE) --out $(DOCS)
	$(PY) $(SCRIPTS)/download_iadb_documents.py --from-csv $(IADB_DOCUMENTS) --out $(DOCS)
	$(PY) $(SCRIPTS)/download_adb_documents.py --from-csv $(ADB_DOCUMENTS) --out $(DOCS)

extract-text:
	$(PY) $(SCRIPTS)/extract_text.py

search: $(SEARCH)
$(SEARCH): $(MANIFEST) $(COMBINED)
	$(PY) $(SCRIPTS)/search_pdfs_for_lead_paint.py

audit: $(AUDIT)
$(AUDIT): $(COMBINED) $(SEARCH)
	$(PY) $(SCRIPTS)/summarize_portfolio.py

$(LAW_STATUS): $(COMBINED)
	$(PY) $(SCRIPTS)/fetch_lead_paint_law_status.py

enrich: $(AUDIT_REG)
$(AUDIT_REG): $(AUDIT) $(LAW_STATUS)
	$(PY) $(SCRIPTS)/enrich_audit.py

chart: $(CHART)
$(CHART): $(AUDIT_REG)
	$(PY) $(SCRIPTS)/plot_by_region.py

# paint_market_surveys.csv is hand-curated (not fetched by a script -- see
# README "Paint market-testing data"), so it's a plain prerequisite, not
# a target with a recipe.
risk-map: $(RISK_MAP)
$(RISK_MAP): $(COMBINED) $(LAW_STATUS) $(MARKET_SURVEYS)
	$(PY) $(SCRIPTS)/plot_lead_paint_risk_map.py

risk-bars: $(RISK_BARS)
$(RISK_BARS): $(COMBINED) $(LAW_STATUS) $(MARKET_SURVEYS)
	$(PY) $(SCRIPTS)/plot_lead_paint_risk_bars.py

verify: $(AUDIT_REG)
	$(PY) $(SCRIPTS)/verify_pipeline.py

all: chart risk-map risk-bars verify
	@echo "Full pipeline complete."

clean:
	rm -f $(OUT)/audit/portfolio_audit*.{csv,md}
	rm -f $(OUT)/audit/projects_by_region.{png,svg}
	rm -f $(OUT)/audit/lead_paint_risk_map.{png,html}
	rm -f $(OUT)/audit/lead_paint_risk_bars.{png,svg}
	@echo "Removed generated outputs in outputs/audit."

# NOTE: paint_market_surveys.csv is hand-curated (not fetched by any
# script) and deliberately NOT removed here -- it would be permanently
# lost, not just regenerated on the next `make`. Only remove the
# script-generated who_lead_paint_law_status.csv.
distclean: clean
	rm -rf $(DOCS)
	rm -f $(OUT)/search/lead_paint_search*.{csv,txt,log}
	rm -f $(OUT)/universe/*.csv
	rm -f $(OUT)/reference/who_lead_paint_law_status.csv
	rm -rf .iati_cache .iati_cache_adb
	@echo "Removed downloaded PDFs and all intermediates."
