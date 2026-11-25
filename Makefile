PYTHON ?= python3

.PHONY: all inputs dashboard explorer census mvr test validate report clean

# Rebuild everything from the files in data/ (no API key needed).
all: inputs dashboard explorer

# Take-up rates, municipal scenario tables and baseline totals.
inputs:
	$(PYTHON) pipeline/02_ptfc_takeup.py
	$(PYTHON) pipeline/03_homestead_scenarios.py
	$(PYTHON) pipeline/04_reallocation_scenarios.py
	$(PYTHON) pipeline/05_baseline_totals.py

# output/dashboard.json
dashboard:
	$(PYTHON) pipeline/06_build_dashboard_data.py

# output/explorer.html: the Relief Explorer showing this run, as one offline file
explorer:
	$(PYTHON) pipeline/08_build_explorer.py

# Re-pull the ACS PUMS sample from the Census API (needs CENSUS_API_KEY).
census:
	$(PYTHON) pipeline/01_pull_census_pums.py

# Rebuild data/derived/mvr_2012_2024.csv from the MRS workbook in data/raw
# (needed only after adding a year to the workbook).
mvr:
	$(PYTHON) pipeline/00_prepare_mvr.py

test:
	$(PYTHON) -m pytest tests -q

# Reproduce the Technical Report's validation against what MRS paid (prints only).
validate:
	$(PYTHON) pipeline/07_validate.py

# Print the Technical Report's figures that are not in output/dashboard.json (prints only).
report:
	$(PYTHON) pipeline/09_report_figures.py

clean:
	rm -rf .pytest_cache model/__pycache__ pipeline/__pycache__ tests/__pycache__
