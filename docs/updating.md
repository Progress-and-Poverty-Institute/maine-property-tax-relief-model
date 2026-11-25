# Updating the model with new data

The model as published is built from:

| Input | Year in this release | File |
|---|---|---|
| Fairness Credit claimants and dollars by town (MRS) | tax year 2024 | `data/raw/ptfc_by_town_2024.xlsx` |
| Municipal Valuation Return (MRS) | 2024 (the FY2025 commitment) | `data/raw/mvr_2012_2024.xlsx` |
| Revenue sharing projections (State Treasurer) | FY2025 | `data/raw/revenue_sharing_projections_fy2025.xls` |
| American Community Survey household sample (Census Bureau) | 2020-2024 5-year file | `data/derived/pums_taxunits.csv` |
| Fairness Credit law | tax year 2026 as current law; tax year 2025 for counting eligibility | `model/ptfc_engine.py` |
| Owner-occupied home values (summary counts from licensed ATTOM records) | the project's ATTOM extract | `data/derived/home_value_counts.json` |

Each can be replaced. This page takes them one at a time: where the file is
read, what to change, and what to check afterwards. The last section covers
the run after any update.

Two rules apply throughout:

- **Keep the layout of the file you replace.** Some readers check the layout
  they depend on (a TOTALS row, a grand-total row that the town rows add up to)
  and stop with a message if it has changed. Other changes, such as a renamed
  column, stop a step with a less specific error.
- **File locations are set in `model/paths.py`.** If a new file has a new name,
  such as `ptfc_by_town_2025.xlsx`, either save it under the old name or change
  the path there.

Commands are given as `make` targets, with the plain `python` equivalent
(for Windows, which has no `make`) in parentheses. Run them from the
repository folder.

## Fairness Credit claimants by town

**File:** `data/raw/ptfc_by_town_2024.xlsx` (`paths.PTFC_BY_TOWN`), MRS's
tabulation of ME 1040 returns claiming the credit, by the town of the filer's
mailing address. Read by `model/ptfc_takeup.py`.

**Layout:** two title rows; a header row (Town, County, # PTFC, $ PTFC); one
row per town; then four rows with no town: out-of-state addresses, addresses
that could not be assigned to a town, towns with fewer than ten returns
(labeled `LESS THAN 10 PTFC RETURNS IN TOWN`, which must match
`SUPPRESSED_LABEL` in `model/ptfc_takeup.py`), and the grand total. Town names
must match the crosswalk, `data/raw/xwalk_muni_to_puma.csv`.

**What it drives:** the claiming rate in each of the ten survey areas (step 02),
and through those rates every dollar figure for the credit.

**Law year.** Claiming rates divide claimants by the households eligible under
`BASELINE` in `model/ptfc_engine.py`, now tax year 2025 law, one year after the
claimants (see VINTAGE at the top of `model/ptfc_takeup.py`; the mismatch moves
dollar figures by 1.6%). With tax year 2025 claimants, the current setting
becomes the matched year. For a later year, add that year's law (below) and
set `BASELINE` to it.

**Check afterwards:**

- Step 02 checks the take-up table and stops if a check fails. Among the
  checks: claimants and dollars must add to the file's own totals (the grand total less out-of-state
  and unassigned returns), all ten areas must be present, statewide take-up must
  fall between 60% and 75%, and the modeled mean credit must be within 10% of
  the actual. It also rebuilds six regional totals two ways, with and without
  the crosswalk, which must agree. A town name the crosswalk does not know
  shows up here.
- The S1-S3 exemptions need re-solving (see "After any update").
- `pipeline/07_validate.py` compares tax year 2024 law with the claimant file.
  For tax year 2025 claimants change `law=E.TY2024` to `law=E.TY2025` in
  `ptfc_validation()`. The fiscal-note comparisons in the same step reproduce
  MRS's 2026 costings, which used tax year 2024 returns, so they are meaningful
  only on the 2024 data.
- The total `MRS actual paid, TY2024` in `output/dashboard.json` is labeled in
  `totals()` in `model/baseline_programs.py`. Change the label there if the
  claimant year changes, and tell whoever maintains the Relief Explorer, which
  reads that key.

## Municipal Valuation Return

**File:** `data/raw/mvr_2012_2024.xlsx`, one sheet per year, named by year.
The model reads the table built from it, `data/derived/mvr_2012_2024.csv`, and
uses the municipal rows of one year, `MVR_YEAR` in `model/ptfc_takeup.py`.

**To add a year:**

1. Add a sheet named for the year (for example `2025`) with the same headings
   as the `2024` sheet: the three columns `Aggregation` (`Muni`, `County` or
   `State`), `County_ofMuni` and `Place`, which were added when the workbook
   was compiled, then MRS's line headings (`Line 6`, `Line 12`, `Line 14a`,
   ..., `TRCF: Line 21`, `TRCF: Line 22`). The lines the model uses are listed
   in `LINES` in `pipeline/00_prepare_mvr.py`.
2. Run `make mvr` (`python pipeline/00_prepare_mvr.py`). It reports any heading
   it cannot find, adds county rows for years that have none, and rewrites
   `data/derived/mvr_2012_2024.csv` (the name stays the same).
3. Set `MVR_YEAR` in `model/ptfc_takeup.py` to the new year.

**What it drives:** every town's taxable value, mill rate, homestead counts and
reimbursements, so every mill-rate change; each survey area's homestead rate and
full-value tax rate; and the S11 and S12 pools (the State's homestead
reimbursement, TRCF Line 21), which `reallocation.gross_pool()` reads from
step 04's town tables.

**Check afterwards:**

- Pair the MVR with the revenue sharing year: MVR year N is the commitment for
  fiscal year N+1, so the 2025 MVR goes with the FY2026 projections.
- Step 04 prints how many towns it matched to the revenue sharing projections
  (481 of 494 in this release). A large drop means town names have changed.
- The S1-S3 exemptions need re-solving (see "After any update").
- The commercial examples take their bills from commitment books, not from the
  MVR. The table in the docstring of `model/commercial_archetypes.py`, which
  compares the model's mill rates with the books', will be out of date.
- The homestead check in `pipeline/07_validate.py` is labeled "MVR 2024".

## Revenue sharing projections

**File:** `data/raw/revenue_sharing_projections_fy2025.xls`
(`paths.REVENUE_SHARING_PROJECTIONS`), the State Treasurer's projected
distribution by town.

**Layout:** headings on the sixth row, including `Municipality Name` and
columns beginning `Rev I Projected`, `Rev II Projected` and `Total Projected`;
one row per town; and a `TOTALS` row.

**What it drives:** the fund totals in `model/fund_totals.py`, rounded to the
nearest $100,000 ($208.5m and $56.1m for FY2025), which size the Scenario 9,
10, 13 and 14 pools and set the Revenue Sharing I total that S15-S19 cut from;
and the town-by-town loss in step 04.

**Check afterwards:** the matched-town count from step 04, as above.

## Census household sample

**File:** `data/derived/pums_taxunits.csv`, written by
`pipeline/01_pull_census_pums.py`. Needs a free Census API key: copy
`.env.example` to `.env` and add the key.

**To move to a later 5-year file:** change `YEAR` at the top of
`pipeline/01_pull_census_pums.py` (2024 means the 2020-2024 file), then run
`make census` (`python pipeline/01_pull_census_pums.py`). Responses are cached
in `data/derived/.pums_cache` under the year, so a new year downloads afresh.
Dollar values are adjusted to the file's final year with the Census
adjustment factors.

**Check afterwards:** the file still uses the ten 2020 survey areas (PUMAs);
if the Census Bureau redraws them, the crosswalk and the area labels in
`model/ptfc_takeup.py` must be rebuilt. Step 02's checks apply. The S1-S3
exemptions need re-solving. `data/derived/muni_acs.csv` and
`muni_classification.csv` (town figures for the worked examples and town labels)
are not rebuilt by the pipeline.

## Fairness Credit law

`model/ptfc_engine.py` holds the law for tax years 2024, 2025 and 2026 as
`Params` (`TY2024`, `TY2025`, `TY2026`). The comments there explain how the
benefit bases are indexed (Chained CPI, rounded down to $50) and reproduce
every published amount; the maximum credits change only by amendment. For a
new year, add for example

```python
TY2027 = replace(TY2026, base_single=..., base_hoh_one=..., base_joint_multi=..., base_senior=...)
```

Two settings choose the law:

- **Current law, the starting point of every scenario:** `baseline_params()` in
  `model/ptfc_recalibrate.py` (now `TY2026`).
- **The law used to count eligible households for the claiming rates:**
  `BASELINE` in `model/ptfc_engine.py` (now `TY2025`). Best set to the
  claimant year.

The homestead exemption ($25,000) and its reimbursement (76%) are current law
in every scenario. If either changes, they appear as `CURRENT_EXEMPTION` in
`model/ptfc_recalibrate.py` and `model/he_resolve_net.py`, `REIMB` in
`model/baseline_programs.py` and `OLD_REIMB` in
`pipeline/04_reallocation_scenarios.py`; search `model/` and `pipeline/` for
`25_000` and `0.76` to find the rest.

## Owner-occupied home values

The homestead scenarios need to know how many homes are worth less than a
proposed exemption, since a home cannot be exempted above its value. The counts
in `data/derived/home_value_counts.json` come from licensed ATTOM records. To
replace them, use any list of owner-occupied homestead properties with a just
(market) value for each, such as a parcel extract, saved as a CSV:

```
python tools/home_value_counts.py homes.csv --value-column just_value
```

Add `--weight-column` if the rows carry weights and `--source "..."` to record
where the values came from. Only the counts are written, never the rows.

## After any update

1. **Run the pipeline:** `make` (Windows: run `python pipeline/02_ptfc_takeup.py`
   through `python pipeline/06_build_dashboard_data.py` in order, then
   `python pipeline/08_build_explorer.py`). Run `make mvr` first if the MVR
   changed. Open `output/explorer.html` to see the new results in the Relief
   Explorer's layout.
2. **Re-solve S1-S3 if asked.** The exemptions of Scenarios 1 to 3 are solved
   to cost the State $35m and then recorded in the code, so a run does not
   silently change a published scenario. When new data move them, step 03 stops
   and prints replacement entries for `HE_SCENARIOS` in
   `model/ptfc_recalibrate.py` and `HE_SCENARIO_FILES` in
   `model/ptfc_takeup.py`. Paste them in and run `make` again.
3. **Check the validation:** `make validate` (`python pipeline/07_validate.py`)
   prints the model against what MRS paid. It will no longer match the
   Technical Report, which used the 2024 data.
4. **Print the report's other figures:** `make report`
   (`python pipeline/09_report_figures.py`) prints every figure the Technical
   Report quotes that is not in `output/dashboard.json`, under the report's
   section headings. With dashboard.json and step 3, it is everything a new
   edition of the report would need.
5. **Run the tests:** `make test` (`python -m pytest tests -q`). Tests marked
   `report` pin figures in the Technical Report and are expected to fail; run
   the rest with `python -m pytest tests -m "not report"`. Those check that the
   outputs rebuild from the inputs, that every scenario meets its constraint
   and that every breakdown adds up, and hold for any data.
6. **Publish:** commit the new files in `data/` and `output/`. The published
   Relief Explorer reads `output/dashboard.json`, so updating it means giving
   its maintainer the new file. Its written text quotes figures from the 2024
   data: that text is in `explorer/data/copy_x.json` and `copy.json`. The local
   build shows it as published, apart from the mill-rate figures in the
   scenario tables, under a banner that says so. The test of the mill-rate
   figures in that text is marked `report`, so it fails until the text is
   updated.
