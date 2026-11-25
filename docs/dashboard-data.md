# Dashboard data: `output/dashboard.json`

`output/dashboard.json` holds every figure in the charts and tables of the
Maine Property Tax Relief Explorer,
<https://landeconomics.org/maine-tax-relief-explorer>. None of them is typed in
by hand; only the Explorer's written text is (see `explorer/README.md`). The
file is written by `pipeline/06_build_dashboard_data.py`, which also checks its
structure (row counts, that archetype cells add up to scenario totals, that
every histogram accounts for every household) and stops if a check fails.
`pipeline/08_build_explorer.py` then builds a local copy of the Explorer from
it, `output/explorer.html`.

This page lists every top-level key and every field, then explains the
conventions you need to read the numbers correctly.

## Terms

| term | meaning |
|---|---|
| PTFC, "the credit" | Maine's Property Tax Fairness Credit, a refundable income tax credit |
| HE | the homestead exemption |
| Homestead Plus | an alternative relief schedule modeled as scenario 14 |
| PUMS, PUMA | the Census Bureau's American Community Survey Public Use Microdata Sample, and its Public Use Microdata Areas. Maine has ten PUMAs |
| MVR | the Municipal Valuation Return, the source for town valuations and mill rates |
| MRS | Maine Revenue Services, the source for actual PTFC claimants and credit paid |
| counted tax | an owner's property tax bill, or 15% of a renter's rent, which 36 M.R.S. §5219-KK treats as rent constituting property tax |
| burden | counted tax, net of the credit, as a share of household income |
| full value mill | a town's nominal mill rate times its certified assessment ratio, so it applies to market value. Stored as a fraction of value (0.0115 = 11.5 mills) |
| weighted | weighted by the PUMS household weight, so counts are Maine households, not survey records |
| claiming-rate weighted | additionally multiplied by the household's PUMA claiming (take-up) rate for the credit |

Dollars are nominal dollars per year unless a field says otherwise.

## Archetype codes: read this before using any `B` code

The file and the Explorer use different codes for the same archetypes, and the
letter `B` means different things in each.

| in the file | in the Explorer | what they are |
|---|---|---|
| `broad` records, ids `B1` to `B6` | Representative archetypes **R1 to R6** | six groups that together cover every Maine household |
| `narrow` records, ids `N1` to `N7` | Burdened archetypes **B1 to B7** | seven groups that together cover every household whose burden is above 6% of income after the credit |

So file `B1` is the Explorer's R1, and the Explorer's B1 is file `N1`. This page uses the
file codes throughout. Where a field is called `a`, it holds one of these ids,
or `"ALL"` for all Maine households.

Archetype membership is fixed under current law, so the households in each
archetype are the same in every scenario.

## Conventions

### 1. State cost is not household relief

`state_cost` is what the State pays, net. `delivered` is what households gain,
net. For credit-only scenarios (4 to 8) they are equal, because a refundable
credit costs the State what households receive. For scenarios that raise the
homestead exemption they differ, because part of the relief is paid by other
property owners through higher mill rates. Equal cost to the State is not equal
relief to households.

### 2. Net, not gross

Every scenario is solved to a net cost. A larger homestead exemption lowers bills,
lower bills mean smaller credits, and the State saves on credits it no longer
pays. Gross figures are not in this file.

### 3. New money against redirected money

Scenarios 1 to 8 spend about $35 million of new State money and have `pool` = 0.
Scenarios 9 to 19 are revenue neutral: they redirect existing State spending
(`pool`) and have `state_cost` at or below zero. Comparing scenarios on the size
of `pool` or `state_cost` is not meaningful; compare them on `delivered` and on
who gains and loses.

### 4. Claiming-rate weighted against full claiming

Not every eligible household claims the credit. The model applies each PUMA's
measured claiming rate (`takeup.by_puma`) to the **credit** only. Changes to
bills are never weighted, because a mill rate or exemption change reaches a
household whether or not it files. This is why a revenue-neutral scenario can
leave a household worse off.

| claiming-rate weighted | full claiming (every eligible household claims) |
|---|---|
| `scenarios.delivered`, `broad.delivered`, `broad_cells.delivered` and `per_hh`, `decile_cells.delivered` and `gain_pct_income`, `puma_cells` dollar and income fields, `narrow_cells.med_gain_delivered` and `mean_gain_delivered` | every burden field (`burden_pre`, `burden_post`, `burden_now`, `burden_scen`, `burden_rows`, `burden_cells`, `burden_threshold`), every credit amount in the archetype profiles and `narrow_cells`, and all of `vignette_cells` (see `vignette_takeup` = 1.0) |

Counts of households better or worse off (`gaining`, `losing`, `share_better`,
`share_worse`, `better`, `worse`, and the `delivered_bins` histograms) count a
household as gaining if its expected, claiming-rate weighted gain is above $1.
Because the claiming rate is never zero, a household whose credit rises is
counted as gaining whether or not it actually claims. These counts describe who
the scenario reaches, not who receives a payment.
Do not put a weighted and an unweighted figure in one table without labeling
which is which.

Scenario 14 (Homestead Plus) uses that program's own claiming rate rather than
today's PTFC rate.

### 5. Homestead status is not observed

The survey does not say which owners hold a homestead exemption. For scenarios
that change the exemption (1 to 3 and 14 to 19), the model computes two outcomes
per owner, as an enrolled homesteader and as a non-enrolled owner, and combines
them using the share of homesteads in the household's area.

- **Sums** (`delivered` and the dollar fields built from it) use the blend.
- **Counts** (`gaining`, `losing`, shares better or worse, histogram bins) count
  each outcome separately and weight the counts by that share, so a household is
  never counted as partly a homesteader. These counts can therefore be fractional.
- **Per-household figures** in `narrow_cells` (dollars and burden), and the
  scenario burden distributions (`burden_cells`, `burden_threshold`), use the
  enrolled-homesteader outcome for every owner. `narrow_cells.basis` labels this.

### 6. PUMA against town

Every household figure is modeled at PUMA level, because the survey places a
household in one of ten areas and no finer. The `towns` block carries **mill rate
changes only**, which the municipal model solves for each of 494 places. A town's
mill rate change is a model result; the model has no households placed in named
towns. Do not combine the two as if they had the same precision.

### 7. Burden and the 6% line

Burden = (counted tax − credit) / household income. Households with income at or
below zero are **excluded** from every burden figure, not placed at zero, because
the ratio is undefined. `burden_undefined` reports how many per archetype.

The burdened (`narrow`) archetypes are defined by a fixed line: burden above 6%
of income after the current-law credit (`threshold`). It is a fixed line, not a
percentile, so the group's definition does not move when the data is revised.
Counts of households "above the line" (`burden_threshold`) also use 6%, not 4%.
"Above" means above 6% after rounding the burden to nine decimal places, the
same rule the burden bins use: the liability ceilings in Scenarios 7 and 8 bring
many households to exactly 6%, and they count as at the line, not above it.
The current-law credit pays tax above 4% of income up to a maximum, so every claimant
whose credit is not capped ends at exactly the 4% line by construction; a count
above 4% would measure how many credits hit the maximum, not how many households
were relieved.

`income_floor` ($45,000) is a category boundary for the broad archetypes and has
no statutory basis. It is never used as a denominator.

### 8. Bins

**Burden bins** (`burden_bin_labels`, `burden_bin_edges`) are right-closed: a
household at exactly 4.00% of income is in "2% to 4%". Read every label as "at or
below" its upper edge. This matters because uncapped claimants sit exactly on the
credit's income line. The six labels have five edges between them.

**Gain or loss bins** (`bin_labels`, `bin_edges`) are eleven fixed bins shared by
every scenario and archetype, so panels compare directly. The middle bin, "no
change", is a change of less than $1 either way (`deadband`), the same rule the
gaining and losing counts use, so a histogram and its counts agree.

## Top-level keys

| key | type | contents |
|---|---|---|
| `generated` | string | build time, UTC, `"YYYY-MM-DD HH:MM UTC"` |
| `threshold` | number | 0.06, the burden line that defines the `narrow` archetypes |
| `income_floor` | number | 45000, the income boundary used in the `broad` rules |
| `senior_age` | integer | 65, the statutory age for the PTFC's senior benefit base and maximum credit |
| `average_mill` | number | today's average full-value mill rate on homesteads, in mills (13.86 in the 2024 MVR). See `mill_change` below |
| `counts` | object | statewide totals, below |
| `totals` | object | current-law program totals, below |
| `takeup` | object | credit claiming rates, below |
| `correlates` | list (7) | what predicts claiming, below |
| `scenarios` | list (19) | one row per scenario |
| `groups` | object | scenario group code to display label |
| `deadband` | number | 1.0. A gain or loss smaller than $1 counts as no change |
| `broad`, `narrow` | lists (6, 7) | archetype profiles under current law |
| `broad_logic`, `narrow_logic` | objects | each archetype's inclusion rule |
| `narrow_notes` | object | prose description of each `narrow` archetype, keyed `N1` to `N7` |
| `broad_cells` | list (6 × 19 = 114) | `broad` archetype by scenario |
| `narrow_cells` | list (7 × 19 = 133) | `narrow` archetype by scenario |
| `decile_cells` | list (14 × 19 × 10 = 2,660) | income decile by archetype by scenario |
| `decile_cuts` | list (10) | upper income bound of each decile |
| `puma_cells` | list (19 × 10 = 190) | PUMA by scenario |
| `puma_order` | list (10) | PUMA codes and labels in display order |
| `towns` | list (494) | mill rate change per town per scenario |
| `town_mill_scenarios` | list (14) | scenario ids that change mill rates |
| `delivered_bins` | list (14 × 19 = 266) | gain or loss histograms |
| `bin_labels`, `bin_edges` | lists (11, 12) | the histogram bins |
| `burden_bin_labels`, `burden_bin_edges` | lists (6, 5) | the burden bins |
| `burden_threshold_pct` | number | 0.06, the same line as `threshold`, used by `burden_threshold` |
| `burden_rows` | list (14 × 2 = 28) | burden distribution before relief and under current law |
| `burden_cells` | list (14 × 19 = 266) | burden distribution under each scenario |
| `burden_threshold` | list (19 × 10 = 190) | households above 6% by income decile |
| `burden_undefined` | list (14) | households excluded from burden figures |
| `archetype_areas` | list (14 × 4 = 56) | where each archetype lives |
| `vignettes` | list (13) | one worked household and real town per archetype |
| `vignette_cells` | list (13 × 19 = 247) | the vignette's arithmetic under each scenario |
| `vignette_takeup` | number | 1.0. Vignettes assume the household claims |
| `commercial` | list (6) | six commercial property examples |
| `commercial_cells` | list (6 × 19 = 114) | their bills under each scenario |

Lists of 14 archetype rows are the 6 `broad`, the 7 `narrow`, and `"ALL"`.

## Statewide constants

### `counts`

| field | meaning |
|---|---|
| `households` | weighted Maine households |
| `owners`, `renters` | weighted owner and renter households |
| `eligible` | weighted households with a positive PTFC under current law |
| `claimants` | actual PTFC claimants reported by MRS, summed over PUMAs |
| `pums_rows` | unweighted survey records in the model |

### `totals`

Current-law program totals, keyed by a description such as `"PTFC delivered at
PUMA take-up (TY2026 law)"`. Values are dollars, except `"PTFC recipients,
delivered (TY2026 law)"`, which is a household count. The keys describe
themselves and may change when the model changes.

### `takeup`

| field | meaning |
|---|---|
| `statewide` | MRS claimants over model-eligible households |
| `derived` | the statewide rate implied by the PUMA rates the model applies; should equal `statewide` |
| `by_puma` | 10 rows, one per PUMA, fields below |

`takeup.by_puma` fields. Shares here are **percentages (0 to 100)**, not fractions.
Characteristics describe eligible households, not all households.

| field | meaning |
|---|---|
| `PUMA`, `area` | PUMA code and label |
| `eligible` | weighted eligible households |
| `claimants` | MRS claimants allocated to the PUMA |
| `takeup_pct` | `claimants / eligible`, percent |
| `credit_paid` | credit MRS paid in the PUMA, dollars |
| `mean_credit_actual` | `credit_paid / claimants` |
| `mean_credit_modelled` | mean modeled credit per eligible household |
| `pct_senior`, `pct_renter` | percent of eligible households that are senior, or rent |
| `pct_no_earnings` | percent with no wage or self-employment income |
| `pct_weak_filing` | percent with no earnings **and** income below the income tax filing threshold. A measure of filing incentive, not of behavior; label it "no earnings and below the filing threshold" |
| `median_income` | median income of eligible households |
| `median_bill` | median property tax bill of eligible owners |
| `towns` | number of towns in the PUMA |

### `correlates`

`characteristic`, `r`: the Pearson correlation between each characteristic of
eligible households and the claiming rate, across the ten PUMAs. With n = 10,
treat differences between correlates as indicative only.

## Scenarios

### `scenarios`

| field | meaning |
|---|---|
| `id` | `"1"` to `"19"`, as strings. Shown in the Explorer as S1 to S19. Scenarios added in `model/local_scenarios.py` follow, from `"20"` |
| `name` | display name |
| `parameter` | what the scenario changes, in words |
| `group` | `cost35` (1 to 8), `realloc` (9 to 14), `october` (15 to 19), or `local` (scenarios added locally) |
| `group_label` | display text for `group`, also in `groups` |
| `family` | mechanism: `HE` (homestead exemption, 1 to 3 and 15 to 19), `PTFC` (credit parameters, 4 to 6), `CEILING` (a cap on tax as a share of income, 7 and 8), `REALLOC` (9 to 13), `HPLUS` (Homestead Plus, 14) |
| `state_cost` | net cost to the State, dollars. About $35m for 1 to 8, 0 for 9 to 13 and 15 to 19, negative (a net saving) for 14 |
| `pool` | existing State spending redirected to fund the scenario, dollars. See below |
| `redirected` | for 15 to 19 and local packages, the State aid the package takes from towns: the Revenue Sharing I cut plus what cutting the homestead reimbursement rate below 76% saves on today's exempt value, at the package's mill rates. `null` for the other scenarios. Shown in the Explorer as "Money redirected" |
| `mill_change` | the statewide average change in mill rates, as a **fraction** (0.0566 = rates rise 5.66% on average). 0 for scenarios that change only the credit. See below |
| `expansion_split` | for 9 to 13, how the credit expansion's discretionary cost divides between the three groups of parameters it moves: `cap` (the maximum credits), `base` (the benefit bases) and `offset` (the income threshold), as fractions summing to 1. `null` for the other scenarios. See below |
| `delivered` | total net gain to households, dollars, claiming-rate weighted |
| `gaining`, `losing` | weighted households better or worse off by more than $1 |

`pool` by group:

| scenarios | `pool` |
|---|---|
| 1 to 8 | 0 |
| 9 to 13 | money freed by abolishing or cutting the program named in `name`, all spent on a wider credit |
| 14 | existing State spending that Homestead Plus replaces; `state_cost` = Homestead Plus cost − `pool` |
| 15 to 19 | the added cost of the wider credit, claiming-rate weighted. The Revenue Sharing I cut in `parameter` funds this plus the homestead change, and is solved so the State breaks even. The whole of the money taken from towns is `redirected` |

`delivered` is smaller than `pool` in the reallocation scenarios because the
program cut raises mill rates and therefore bills.

**`mill_change`** is the one statewide mill measure, used for every scenario in
the Relief Explorer and the Technical Report: the average of the towns'
proportional changes (the `s` fields in `towns`), each town weighted by the
property tax it levies today (its MVR commitment). In mills it is
`mill_change * average_mill`, which is how the scenario tables print it
("Increase of 0.78 mills (+5.66%)"). `average_mill` weights each town's
full-value rate by its homestead count, as the household model does within each
survey area. For Scenarios 1 to 3, `parameter` shows a different figure, the
statewide mill change the household model applies to bills, which is weighted
by taxable value after the exemption.

**`expansion_split`** is a Shapley decomposition (`reallocation.Expansion.split`):
each group's share is its marginal cost averaged over every order in which the
three groups could be moved, so the shares do not depend on an arbitrary
order. It covers the discretionary cost only, not the automatic rise in credits
that the higher bills cause before any parameter moves.

### `groups`

Maps `cost35`, `realloc` and `october` (and `local`, when scenarios have been added locally) to their display labels.

## Archetypes

### `broad` and `narrow` (profiles under current law)

| field | meaning |
|---|---|
| `archetype` | id and label, e.g. `"N1 Older owner, lives alone"`. The id is the first word |
| `households` | weighted households |
| `n` | **unweighted** survey records. Small values mean small samples |
| `base_is` | `"owners"` or `"renters"`, whichever is the group's majority tenure |
| `share_of_base` | `households` as a share of all owners or all renters, per `base_is` |
| `med_age` | median age of the householder |
| `med_income` | median household income |
| `med_home` | median home value for an owner group; median **annual rent** for a renter group (check `base_is`) |
| `med_tax` | median counted tax |
| `burden_pre` | median burden before the credit |
| `burden_post` | median burden after the full current-law credit |
| `pct_eligible` | share of the group with a positive credit |
| `med_credit` | median credit **among households with one** |
| `pct_at_cap` | share of credit recipients limited by the maximum credit |
| `pct_at_base` | share of credit recipients limited by the benefit base (the most tax the credit will count) |
| `delivered` | `broad` only. Today's credit delivered to the group, claiming-rate weighted, dollars. Not a scenario figure |

`burden_pre` and `burden_post` are medians of two separately sorted
distributions. The gap between them is the group median moving, not the typical
household's saving.

### `broad_logic`, `narrow_logic`

Inclusion rule per archetype id, written with PUMS variable names: `TEN` tenure
(1, 2 owned; 3, 4 rented), `AGEP` householder age, `HHT` household type (4, 6 =
householder living alone), `n_dep` dependents, `income` household income,
`home_value`. A `narrow_logic` rule starting `...` repeats the start of `N1`'s
rule. `narrow` rules apply only within the burdened group, and dependents are
tested before home value, so a family with children in a high-value home is `N5`,
not `N6`.

### `broad_cells`

| field | meaning |
|---|---|
| `s`, `a` | scenario id, `broad` archetype id |
| `households` | weighted households in the archetype |
| `delivered` | net gain, dollars, claiming-rate weighted. A scenario's six cells sum to its `delivered` |
| `per_hh` | `delivered / households` |
| `gaining`, `losing` | weighted households better or worse off by more than $1 |

Use these for distribution: they are expected values summed over many households.

### `narrow_cells`

One archetypal household's view of each scenario.

| field | meaning |
|---|---|
| `s`, `a` | scenario id, `narrow` archetype id |
| `basis` | `"enrolled homesteader"`: owner archetype under a scenario that changes the homestead exemption, so dollar and burden fields assume the owner is enrolled. `"full statutory credit"`: no homestead choice arises (a renter archetype, or a scenario that leaves the exemption alone). Applies to the dollar and burden fields only. Despite the wording, the gain fields below are claiming-rate weighted under either label |
| `med_gain_delivered` | median per-household change: credit change × claiming rate, minus bill change |
| `mean_gain_delivered` | weighted mean of the same change. The Explorer's "average relief per household" |
| `share_better`, `share_worse` | share of the archetype better or worse off by more than $1, blended across homestead outcomes (convention 5) |
| `med_tax_base`, `med_tax_scen` | median counted tax now and under the scenario |
| `burden_now`, `burden_scen` | median burden now and under the scenario |
| `credit_now`, `credit_scen` | median credit among recipients, now and under the scenario |
| `pct_eligible`, `pct_at_cap`, `pct_at_base` | as in the profiles, under the scenario |

A row can carry a blended share beside an enrolled-homesteader dollar figure.
That is intended.

### `decile_cells`, `decile_cuts`

Income deciles are weighted deciles of household income across all Maine
households. `decile_cuts` gives the highest income in each decile; the last is
the top income in the data.

| field | meaning |
|---|---|
| `s`, `a`, `d` | scenario id, archetype id or `"ALL"`, decile 1 to 10 |
| `households` | weighted households in the cell |
| `delivered` | net gain, dollars, claiming-rate weighted |
| `gain_pct_income` | the cell's total net gain over its total income (a ratio of totals), excluding households with income at or below zero. `null` where the cell has no positive income |

## Geography

### `puma_cells`, `puma_order`

`puma_order` lists `puma` (2020 PUMA code), `label` and `rank`. `rank` runs 1
(most rural) to 10 (most urban) and is the display order.

| field | meaning |
|---|---|
| `s`, `puma`, `label`, `rank` | scenario and area |
| `households` | weighted households |
| `delivered` | net gain, dollars, claiming-rate weighted |
| `share_of_delivered` | the area's share of the scenario's `delivered`. **Can be negative**: an area can lose on net while the state gains |
| `per_hh` | `delivered / households` |
| `gain_pct_income` | the area's total net gain over its total income. Use this for display |
| `net_pct_income` | mean of each household's own net gain over income. Dominated by very low incomes; prefer `gain_pct_income` |
| `bill_pct_income` | mean of each household's bill change over income, ignoring the credit |
| `better`, `worse` | share of households better or worse off by more than $1 |

The three `*_pct_income` fields exclude households with income at or below zero.

### `towns`, `town_mill_scenarios`

| field | meaning |
|---|---|
| `town` | normalized upper-case place name (the join key) |
| `service` | service-center classification, e.g. `"Primary service centre"`, `"Unorganised territory"` |
| `size` | size class, e.g. `"Small Town"`, `"City"`, `"UT"` |
| `economy` | economic type, e.g. `"bedroom"`, `"tourism"`, `"unclassified"` |
| `s1`, `s2`, `s3`, `s9` to `s19` | proportional change in the town's mill rate as a **fraction** (0.0635 = the rate rises 6.35%) |

`town_mill_scenarios` lists the scenarios with a mill rate change (1 to 3 and 9
to 19). Scenarios 4 to 8 change only the credit and move no mill rate, so they
have no column.

**`null` is not zero.** Thirteen places (twelve unorganized territories and Moro
Plantation) are not in the municipal runs for scenarios 9, 10, 13 and 14 and
carry `null` there: not modeled, which is different from no change. `s10` is a
true `0` for towns that receive no Revenue Sharing II. One place has `null`
`service`, `size` and `economy` because it has no classification.

### `archetype_areas`

| field | meaning |
|---|---|
| `a`, `family` | archetype id or `"ALL"`; `broad`, `narrow` or `all` |
| `area` | `Rural`, `Service`, `South` or `Portland`, a four-way grouping of the ten PUMAs |
| `share` | share of the archetype living in that area; sums to 1 per archetype |

Always show an archetype's shares beside the `"ALL"` row. "47% rural" means
little without the statewide figure.

## Distributions

### `delivered_bins`, `bin_labels`, `bin_edges`

| field | meaning |
|---|---|
| `s` | scenario id |
| `a`, `family` | archetype id or `"ALL"`; `broad`, `narrow` or `all` |
| `bins` | 11 weighted household counts aligned to `bin_labels` |

`bin_edges` holds the 12 boundaries in dollars, `null` for the open ends. Each row
accounts for every household in its group. Positive bins sum to the gaining count
and negative bins to the losing count.

### `burden_rows`, `burden_cells`, `burden_undefined`

| field | meaning |
|---|---|
| `a`, `family` | archetype id or `"ALL"`; `broad`, `narrow` or `all` |
| `series` | `burden_rows` only: `before_relief` or `now` |
| `s` | `burden_cells` only: scenario id |
| `bins` | 6 weighted household counts aligned to `burden_bin_labels` |

- `before_relief` removes both the homestead exemption and the credit, with town
  mill rates recalculated for the exemption coming off the tax base.
- `now` is current law.
- `burden_cells` is the same distribution under each scenario.

`burden_undefined` (`a`, `family`, `households`) gives the weighted households
excluded from these bins because income is at or below zero. Subtract them before
presenting the bins as covering a whole group.

### `burden_threshold`

| field | meaning |
|---|---|
| `s`, `d` | scenario id, income decile |
| `now` | weighted households in the decile with burden above `burden_threshold_pct` under current law |
| `scen` | the same count under the scenario |

## Vignettes

Each archetype has one worked example: a real survey household from the
archetype, matched on income, home value or rent, age and household size, placed
in a real Maine town whose full value mill rate fits the archetype's medians.
Broad archetypes weight age and household size more heavily, because they claim
to be typical; burdened archetypes weight burden more heavily. Two households
(`B6` and `N4`) were chosen by hand because scoring picked a household receiving
no credit, which would have misrepresented the archetype. The thirteen towns are
distinct and cover all ten PUMAs.

### `vignettes`

| field | meaning |
|---|---|
| `archetype`, `family` | archetype label; `broad` or `narrow` |
| `town`, `key`, `county`, `pop` | the town's display name, its join key into `towns`, county, population |
| `puma`, `puma_label` | the town's PUMA |
| `service` | service-center classification |
| `households` | weighted size of the **archetype**, not the town |
| `town_mill` | the town's full value mill rate, as a fraction (0.0185 = 18.5 mills) |
| `target_mill` | the full value mill rate the archetype's medians imply: median tax over (median home value − exemption). For renter archetypes, the rate the archetype faces |
| `mill_gap` | `town_mill − target_mill`, published so the fit is visible |
| `town_home_value`, `town_income` | the town's ACS medians. Reported for transparency; not used to choose the town |
| `target_home_value`, `target_income` | the archetype's medians, same basis (`target_home_value` is `null` for the renter archetypes) |
| `s1` ... `s19` | the town's proportional mill change per scenario, as in `towns`. No columns for 4 to 8 |
| `overridden` | `true` if the town was set by hand rather than scored |

### `vignette_cells`

The vignette household's arithmetic under each scenario, assuming it claims the
credit (`vignette_takeup` = 1.0).

| field | meaning |
|---|---|
| `a`, `s`, `town` | archetype id, scenario id, town display name |
| `owner` | `true` for an owner, `false` for a renter |
| `income` | household income |
| `home_value`, `rent_annual` | home value (0 for renters), annual rent (0 for owners) |
| `town_mill` | the town's full value mill rate, as a fraction |
| `town_dmill` | the scenario's proportional change in it, as a fraction |
| `bill_base`, `bill_scen` | property tax bill now and under the scenario; 0 for renters |
| `counted_tax_base`, `counted_tax_scen` | counted tax now and under the scenario. The only figure comparable between owners and renters |
| `credit_base`, `credit_scen` | full credit now and under the scenario |
| `net` | `(credit_scen − credit_base) − (bill_scen − bill_base)` |
| `burden_base`, `burden_scen` | burden now and under the scenario |

Two things to state wherever a vignette appears:

- **The bill is computed, not reported.** It is (home value − homestead
  exemption) × the town's full value mill rate, consistent with the rest of the
  model, rather than the household's own reported tax.
- **Every mill rate is a full value rate.** A town assessing at 80% of market
  value with a nominal 8 mills has an effective 6.4 mills on market value.

## Commercial examples

Six real commercial parcels. Unlike every other figure in this file, their base
bills are **not computed by the model**: they come from each town's commitment
book, because a parcel pays its town's nominal rate on assessed value, and the
model's full value rates would not reproduce the actual bill. The scenario changes
apply the model's proportional mill change to that actual bill.

### `commercial`

| field | meaning |
|---|---|
| `id` | `C1` to `C6` |
| `label` | display name, e.g. `"A repair shop in Gardiner"` |
| `town` | municipality, display name |
| `assessed` | the town's assessed value for the parcel |
| `billed` | the annual bill from the town's commitment book |
| `units` | dwelling units: 1 for a single commercial tenant, 10 for `C6` |
| `billed_per_unit` | `billed / units`. Only meaningful for `C6` |

### `commercial_cells`

| field | meaning |
|---|---|
| `a`, `s`, `town`, `units` | commercial id, scenario id, town, dwelling units |
| `mill_pct` | the scenario's change in the town's mill rate, in **percent** (0.356 = a 0.356% rise; note `towns` stores the same quantity as a fraction). Zero for scenarios 4 to 8, and for scenario 10 in towns with no Revenue Sharing II |
| `bill_base`, `bill_scen` | annual bill now and under the scenario |
| `change`, `change_per_unit` | `bill_scen − bill_base`, and that divided by `units` |

## Units at a glance

| quantity | stored as |
|---|---|
| shares, burdens, claiming rates (except `takeup.by_puma`) | fraction, 0 to 1 |
| `takeup.by_puma` percentages | percent, 0 to 100 |
| mill rates (`town_mill`, `target_mill`) | fraction of value |
| mill changes in `towns`, `vignettes`, `vignette_cells.town_dmill` | proportional change, fraction |
| `commercial_cells.mill_pct` | proportional change, percent |
| money | dollars per year |
| household counts | weighted households (fractional where homestead outcomes are blended) |
| `n` | unweighted survey records |
