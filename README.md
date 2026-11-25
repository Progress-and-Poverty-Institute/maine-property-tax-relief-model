# Maine Property Tax Relief Model

A model of how changes to Maine's property tax relief programs would affect
households, municipalities and the State budget. Built by the
[Progress and Poverty Institute](https://progressandpovertyinstitute.org) and the
[Center for Land Economics](https://landeconomics.org) for Maine's
[Real Estate Property Tax Relief Task Force](https://legislature.maine.gov/real-estate-property-tax-relief-task-force)
(Resolve 2025, c. 108).

**Results: [Maine Property Tax Relief Explorer](https://landeconomics.org/maine-tax-relief-explorer)**

This repository contains the code and data that produce every figure in the
Relief Explorer and the accompanying Technical Report. Running it rebuilds
`output/dashboard.json`, the file the Explorer reads, and
`output/explorer.html`, a copy of the Explorer that shows the run's results and
opens offline, so new data or new scenarios can be explored without publishing
anything.

## What it models

Two programs, and the municipal budgets they interact with:

- **Property Tax Fairness Credit** (36 M.R.S. §5219-KK), a refundable income tax
  credit for property tax or rent above a share of income.
- **Homestead exemption** ($25,000 of assessed value for a primary residence,
  76% reimbursed to the town by the State), along with the BETE reimbursement
  and municipal revenue sharing, which the scenarios draw on.

The model has two halves that are solved together:

1. **Municipal.** For each of Maine's 494 municipalities, the 2024 Municipal
   Valuation Return gives the tax base, mill rate and State payments. Under each
   scenario the town re-solves its mill rate so that it still raises its budget.
   State reimbursements are a mill rate times a value, so they move with the mill.
2. **Household.** Each household in the Census Bureau's American Community
   Survey sample (2020-2024, 30,029 Maine households) gets its actual property
   tax or rent, its mill-rate change, and the Fairness Credit it qualifies for,
   computed from the statute. Credit dollars are counted at the share of
   eligible households that claim today in each of Maine's ten survey areas (PUMAs),
   measured from Maine Revenue Services' claimant counts by town.

Town mill-rate changes reach households through their survey area, weighted by
levy. The State's cost of each scenario is net: a larger exemption lowers tax
bills, which lowers the credits the State pays.

**Scenarios** (19):

| | Scenarios | Constraint |
|---|---|---|
| S1-S8 | Raise the homestead exemption, change its reimbursement, raise the credit's benefit bases or maximum, or replace it with a liability ceiling | $35 million of new State spending each |
| S9-S14 | Redirect revenue sharing or the homestead reimbursement into a larger credit; replace existing relief with Homestead Plus | No new State spending: paid for from existing relief programs |
| S15-S19 | Combined exemption and credit packages considered by the Task Force | No new State spending: paid for by a Revenue Sharing I cut and, in four of the five, a cut in the homestead reimbursement to 50% |

**Archetypes** (19): six Representative households that together cover all of
Maine, seven Burdened households (property tax above 6% of income), and six
commercial properties in named towns.

## Running it

### Get the code

Clone the repository with Git, or download it from GitHub as a ZIP (the green
"Code" button) and unzip it. Every command below is run from inside the
repository folder:

```
git clone https://github.com/Progress-and-Poverty-Institute/maine-property-tax-relief-model.git
cd maine-property-tax-relief-model
```

### Set up Python

Python 3.11 or later. Tested with Python 3.11 and 3.12, pandas 3.0 and 3.1 and
numpy 2.4, on Linux and Windows. Check which Python your computer runs:

```
python --version
```

On Windows, if `python` opens the Microsoft Store or reports a version older
than 3.11, install Python from <https://www.python.org/downloads/> and use the
`py` launcher in place of `python` in every command below (`py -3.12` picks a
particular version).

Installing the requirements upgrades pandas and numpy for everything else that
uses the same Python. To keep the model's packages separate, create a virtual
environment first, once:

```
python -m venv .venv
```

then use `.venv\Scripts\python` (Windows) or `.venv/bin/python` (macOS, Linux)
in place of `python` below, or activate the environment
(`.venv\Scripts\Activate.ps1` in PowerShell, `source .venv/bin/activate`
elsewhere). If PowerShell refuses to run the activation script, use the first
form.

### Run

```bash
pip install -r requirements.txt
make            # rebuild every table, output/dashboard.json and output/explorer.html
make test       # check that the outputs rebuild and match the Technical Report
make validate   # reproduce the Technical Report's checks against what MRS paid
make report     # print the Technical Report's figures that are not in dashboard.json
```

Windows has no `make`. From the repository folder, the same run is:

```
pip install -r requirements.txt
python pipeline/02_ptfc_takeup.py
python pipeline/03_homestead_scenarios.py
python pipeline/04_reallocation_scenarios.py
python pipeline/05_baseline_totals.py
python pipeline/06_build_dashboard_data.py
python pipeline/08_build_explorer.py
python -m pytest tests -q
python pipeline/07_validate.py
python pipeline/09_report_figures.py
```

The six `pipeline` steps are `make`; the last three lines are `make test`,
`make validate` and `make report`. Together, `output/dashboard.json` and the
output of `make validate` and `make report` hold every figure in the Technical
Report. The pipeline takes a few minutes; the tests take from about
half a minute to about three minutes, depending on the computer. The results are
the same on every computer to floating-point precision (about 15 significant
figures).

`make` needs no API key: the Census sample is included in `data/derived/`. To
pull it again from the Census API, copy `.env.example` to `.env`, add a free key
from <https://api.census.gov/data/key_signup.html>, and run `make census`.
`make mvr` rebuilds the municipal table from the MRS workbook in `data/raw/`;
it is needed only after adding a year to the workbook.

### Pipeline

| Step | Writes | Reads |
|---|---|---|
| `00_prepare_mvr.py` | `data/derived/mvr_2012_2024.csv` | MVR workbook (run by `make mvr` only) |
| `01_pull_census_pums.py` | `data/derived/pums_taxunits.csv` | Census API (key required; run by `make census` only) |
| `02_ptfc_takeup.py` | `data/derived/takeup/` | ACS sample, Fairness Credit claims by town |
| `03_homestead_scenarios.py` | `data/derived/scenarios/s1-s3_*.csv` | MVR, ACS sample, take-up |
| `04_reallocation_scenarios.py` | `data/derived/scenarios/s9-s14_*.csv` | MVR, revenue sharing projections |
| `05_baseline_totals.py` | `data/derived/baseline_totals.csv` | all of the above |
| `06_build_dashboard_data.py` | `output/dashboard.json` | all of the above |
| `07_validate.py` | nothing; prints the validation | ACS sample, Fairness Credit claims by town, MVR, MRS fiscal-note workbooks |
| `08_build_explorer.py` | `output/explorer.html` | `output/dashboard.json`, the Explorer's files in `explorer/` |
| `09_report_figures.py` | nothing; prints the report's figures not in `dashboard.json` | all of the above (run by `make report` only) |

Step 06 also writes the town tables for S15-S19 to `data/derived/scenarios/`
and checks that every breakdown adds back to its scenario's total. Step 03
re-solves the S1-S3 exemptions and checks them against the values recorded in
`model/ptfc_recalibrate.py`; if new data move them, it stops and prints the
replacement values (see [docs/updating.md](docs/updating.md)).

`model/validate_against_policyengine.py` is an optional check that compares the
model's credit formula with [PolicyEngine US](https://github.com/PolicyEngine/policyengine-us)
household by household (`pip install policyengine-us`). PolicyEngine releases
that lack the indexed tax year 2025 benefit bases differ by $50 to $150 for
the households those bases affect.

### What a run produces

| Where | What |
|---|---|
| `output/explorer.html` | The Relief Explorer showing this run: the published Explorer's pages, charts and tables, in one file that opens in a browser without an internet connection. A banner marks it as a local build. |
| `output/dashboard.json` | Every figure on the Relief Explorer: scenario costs, results by archetype, income decile and survey area, burden counts, town mill-rate changes, worked examples. Fields are described in [docs/dashboard-data.md](docs/dashboard-data.md). |
| `data/derived/takeup/` | `ptfc_takeup_by_puma.csv`: for each survey area, eligible households, claimants, claiming rate, credit paid and household characteristics. `ptfc_takeup_correlates.csv`: how those characteristics correlate with the claiming rate. |
| `data/derived/scenarios/` | One table per scenario with a row per town: tax base, mill rate before and after, and the State's reimbursements. S1-S3 are written by step 03, S9-S14 by step 04, S15-S19 by step 06. |
| `data/derived/baseline_totals.csv` | Current programs in dollars: the credit at full claiming and at today's claiming rates, against what MRS paid; the homestead exemption's value, its reimbursement and its effect through mill rates. |
| The console | Each step prints its checks and headline figures: the claiming rate (02), the S1-S3 exemptions and their cost (03), the money freed and mill-rate change in S9-S14 (04), the baseline totals (05), each scenario's total (06), the validation (07) and the report's other figures (09). |

## Using it for new questions

- **A policy of your own:** [docs/new-policy.md](docs/new-policy.md) shows
  where each scenario is defined and works through examples you can run: a
  change to the Fairness Credit, a revenue-neutral package like S15-S19, and
  how to add either to the local Explorer (`model/local_scenarios.py`).
- **New data** (claimants for a later tax year, a new Municipal Valuation
  Return, new revenue sharing projections, a later Census sample, a new law
  year): [docs/updating.md](docs/updating.md) takes each input in turn.

## Layout

```
model/       the model (credit formula, municipal model, scenarios, archetypes)
pipeline/    the steps above
tools/       home_value_counts.py: rebuilds the home-value counts from a parcel list
explorer/    the Relief Explorer's page, script and text, for output/explorer.html
data/        inputs and intermediate tables; sources in data/README.md
output/      dashboard.json (fields in docs/dashboard-data.md) and explorer.html
docs/        dashboard-data.md, new-policy.md, updating.md
tests/       reproduction checks
```

## Data

Sources, coverage and preparation are in [data/README.md](data/README.md). In
short: Maine Revenue Services (Municipal Valuation Returns 2012-2024, Fairness
Credit claims by town for tax year 2024), the Maine State Treasurer (FY2025
revenue sharing projections), and the Census Bureau (ACS microdata and town
estimates). Two sources enter only as summaries: licensed ATTOM property
records, as counts of homes by value band, and six properties' figures from
municipal commitment books.

## Limits

- The Census sample locates households only to one of ten survey areas, each
  covering dozens of towns. Town mill-rate changes are computed town by town;
  household figures for a town describe a typical household of its survey area
  living there, not the households who actually live there.
- The survey does not record who holds a homestead exemption. Owner-occupiers
  are modeled with and without one, weighted by each area's enrollment rate.
- Results are static: no change in home values, rents, budgets or claiming
  behavior in response to a reform.

## License

Code, including the Relief Explorer's files in `explorer/`: MIT (see
[LICENSE](LICENSE)). Data files keep the terms of their sources.

## Citation

Progress and Poverty Institute and Center for Land Economics (2026). *Maine
Property Tax Relief Model*, version 1.0. https://github.com/Progress-and-Poverty-Institute/maine-property-tax-relief-model
