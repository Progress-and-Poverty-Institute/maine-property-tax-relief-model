"""File locations used by the model and the pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
DERIVED = DATA / "derived"
OUTPUT = ROOT / "output"

# Source files
MVR_XLSX = RAW / "mvr_2012_2024.xlsx"
PTFC_BY_TOWN = RAW / "ptfc_by_town_2024.xlsx"
REVENUE_SHARING_PROJECTIONS = RAW / "revenue_sharing_projections_fy2025.xls"
XWALK_MUNI_PUMA = RAW / "xwalk_muni_to_puma.csv"
MRS_FISCAL_NOTES = RAW / "mrs_ptfc_fiscal_notes_2026-04-16.xlsx"
MRS_PTFC_SCENARIOS = RAW / "mrs_ptfc_scenarios_c_d.xlsx"

# Prepared inputs
MVR = DERIVED / "mvr_2012_2024.csv"
PUMS = DERIVED / "pums_taxunits.csv"
PUMS_CACHE = DERIVED / ".pums_cache"
MUNI_ACS = DERIVED / "muni_acs.csv"
MUNI_CLASSIFICATION = DERIVED / "muni_classification.csv"
HOME_VALUE_COUNTS = DERIVED / "home_value_counts.json"   # value-cap counts (ATTOM summary)

# Intermediate tables written by the pipeline
SCENARIO_DIR = DERIVED / "scenarios"
TAKEUP_DIR = DERIVED / "takeup"
BASELINE_TOTALS = DERIVED / "baseline_totals.csv"

# Final output
DASHBOARD_JSON = OUTPUT / "dashboard.json"
