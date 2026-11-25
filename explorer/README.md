# The Relief Explorer, for local builds

These are the files of the Maine Property Tax Relief Explorer as published at
<https://landeconomics.org/maine-tax-relief-explorer> (copied 24 November 2026),
so that `make` (step `pipeline/08_build_explorer.py`) can build a copy of it that
shows any model run: `output/explorer.html`, one file that opens in a browser
with no internet connection.

| File | What it is |
|---|---|
| `index.html`, `styles.css`, `app.js` | the page, its styles and the script that draws every exhibit from the dashboard data |
| `assets/` | the two logos and the map of the survey areas |
| `data/copy.json` | the About page and the scenario table's program columns |
| `data/copy_x.json` | the scenario and archetype write-ups and the page introductions |

The dashboard data itself is not kept here: the build reads this run's
`output/dashboard.json`.

**Changes from the published files.** `app.js`, `styles.css`, `index.html` and the
images are unchanged; the build step changes two lines of `app.js` in its output
so the script finds its data inside the page rather than on a web server. The
written text has been checked against the released model, figure by figure, and
corrected where they disagreed (November 2026):

- **Figures:** the Gardiner repair shop's rate and bill (25.6 mills, $7,040, and
  its bill under each scenario); the money each Task Force scenario redirects
  (the reimbursement cut valued at the scenarios' own mill rates, so $30.5m to
  $31.6m rather than $28.5m, and $73.5m to $161.0m in all); Scenario 3's
  exemption increase ($31,400); R6's share above 4% after the credit (3%); B7's
  rent-above-income share (63%); the summary table's parameters for Scenarios
  4, 5, 8 and 9 to 13; nine worked household examples whose bill or credit
  change was a difference of rounded figures rather than the rounded change;
  two figures in the key findings for B1 and B2; and the About page's
  validation figures.
- **Mill rates:** every statewide mill-rate change is now on one measure
  (`mill_change` in `docs/dashboard-data.md`). This changed the figures for
  Scenarios 1, 3, 14, 15, 17, 18 and 19 and replaced the note that explained
  the two measures used before.
- **Comparisons:** claims of "highest", "most" or "only" that the data do not
  support (Scenario 18's credit and first decile; archetypes B1, B4, B5, B6 and
  B7; R1 and R3 under reallocation; the Bangor apartments' tenants).
- **About page:** the Homestead Engine description (one statewide distribution
  of home values, not town-by-town records, so the "Parcel Engine" test is
  removed); the limitations on take-up, town mill rates and the age of the
  data; the homestead validation, now described as a consistency check as in
  the Technical Report; and the scenario calibration note.

The build fills the mill-rate figures in the scenario tables from the run.
Any other disagreement between the text and a new model run is not corrected
automatically: see the banner on every local build. For the published run,
`tests/test_explorer.py` checks the mill-rate figures in the prose as well.

**Credits.** The Explorer was built by the Center for Land Economics with the
Progress and Poverty Institute; its written text is by the Progress and Poverty
Institute. The logos belong to their organizations.
