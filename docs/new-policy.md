# How to model a new policy

The model can price policies beyond the nineteen scenarios in the Relief Explorer.
This page shows where the existing scenarios are defined and gives worked
examples: a single change to the Fairness Credit, a revenue-neutral package of
the kind the Task Force considered, and how to see either in a local copy of the
Relief Explorer.

Examples 1 and 2 run outside the pipeline and change no file. Save each as a `.py`
file in the repository folder and run it with `python` from there (for
example `python my_policy.py`). Run `make` once first, or use the tables that
ship in `data/derived/`.

## Where the scenarios are defined

| Scenarios | Defined in | What to change |
|---|---|---|
| S1-S3, homestead exemption and reimbursement | `model/he_resolve_net.py` (solver), `model/ptfc_recalibrate.py` (`HE_SCENARIOS`, the solved values) | Exemption amount and reimbursement rate; step 03 re-solves them |
| S4-S6, Fairness Credit | `model/scenarios.py` (`CANONICAL`) | Benefit bases, maximum credits, income threshold |
| S7-S8, liability ceilings | `model/ceiling_redesign.py` (`recommended`) | Ceiling as a share of income, age test, income phase-out, value limit |
| S9-S13, aid to towns redirected to the credit | `model/reallocation.py` (`SCENARIOS`, `gross_pool`, `Expansion`) | Which State aid is withdrawn; how the credit expands |
| S14, Homestead Plus | `model/homestead_plus.py` | Burden thresholds and State shares |
| S15-S19, Task Force packages | `model/bundle_scenarios.py` (end of `load()`), priced by `model/task_force.py` (`Combo`) | Exemption, reimbursement rate, credit parameters; the Revenue Sharing I cut is solved |

The Fairness Credit's parameters are the fields of `Params` in
`model/ptfc_engine.py`: the four benefit bases (`base_single`, `base_hoh_one`,
`base_joint_multi`, `base_senior`), the two maximum credits (`cap_under65`,
`cap_senior`), the income threshold (`rate_income`, 4%) and the share of rent
counted as property tax (`rate_rent`, 15%). Current law (tax year 2026) is
`ptfc_recalibrate.baseline_params()`, which every scenario starts from.

## Example 1: one change to the Fairness Credit

Raise the maximum credit for households 65 and over from $2,000 to $2,500,
and report the State's cost and who receives the money.

```python
import sys
sys.path.insert(0, "model")

from dataclasses import replace
import numpy as np
import pandas as pd
import ptfc_recalibrate as R

m = R.Model()                              # households, current law, claiming rates
new = replace(m.p0, cap_senior=2_500.0)    # the policy: 65+ maximum $2,000 -> $2,500

d = m.delta(new)                           # change in each household's credit if claimed
gain = d * m.tau_h                         # expected change, at today's claiming rates
print(f"State cost:         ${(gain * m.W).sum() / 1e6:,.1f}m a year")
print(f"Households helped:  {m.W[d > 0].sum():,.0f} eligible, "
      f"{(m.W * m.tau_h)[d > 0].sum():,.0f} expected to claim")

# Who gets the money: share by household income decile (all Maine households)
inc = m.df["income"].to_numpy()
o = np.argsort(inc, kind="stable")
decile = np.empty(len(inc), int)
decile[o] = np.clip((np.cumsum(m.W[o]) / m.W.sum() * 10).astype(int), 0, 9) + 1
dollars = pd.Series(gain * m.W).groupby(decile).sum()
print((100 * dollars / dollars.sum()).round(1).rename("% of dollars"))
```

With the data in this repository it prints a cost of $5.6m a year, 21,118
eligible households helped (14,596 expected to claim), and 92% of the dollars
in the bottom three income deciles.

`m.W` is each survey household's weight (the number of Maine households it
represents) and `m.tau_h` its area's claiming rate. Dollar figures are
weighted by claiming, as in the Explorer; counts of eligible households are
not. Any other field of `Params` can be changed the same way, several at once:
`replace(m.p0, cap_under65=1_750.0, rate_income=0.035)`.

## Example 2: a revenue-neutral package

Raise the homestead exemption to $40,000, keep the 76% reimbursement, raise the
maximum credits to $2,250 (under 65) and $3,000 (65 and over), and pay for it
by cutting Revenue Sharing I. The cut is solved so the State's net cost is zero,
as in Scenarios 15 to 19.

```python
import sys
sys.path.insert(0, "model")

from dataclasses import replace
import numpy as np
import pandas as pd
import ptfc_recalibrate as R
import ptfc_takeup as T
import task_force as TF
import fund_totals as F

m = R.Model()

# The package: exemption $40,000 with the 76% reimbursement kept, and the
# maximum credits raised to $2,250 (under 65) and $3,000 (65+).
exemption, rate = 40_000.0, 0.76
p = replace(m.p0, cap_under65=2_250.0, cap_senior=3_000.0)

def net_cost(cut):
    """The State's net change in cost for a given Revenue Sharing I cut."""
    return TF.Combo(m, exemption=exemption, rate=rate, revi_cut=cut).fix(p)

# Solve the cut that leaves the State whole (net cost zero), by bisection.
lo, hi = 0.0, F.revenue_sharing()["rev_i"]
if net_cost(hi) > 0:
    sys.exit("Abolishing Revenue Sharing I would not pay for this package.")
for _ in range(40):
    mid = (lo + hi) / 2
    lo, hi = (lo, mid) if net_cost(mid) < 0 else (mid, hi)
cut = (lo + hi) / 2

pkg = TF.Combo(m, exemption=exemption, rate=rate, revi_cut=cut)
pkg.fix(p)
print(f"Revenue Sharing I cut:            ${cut / 1e6:,.1f}m")
print(f"  homestead reimbursement change: ${pkg.state['reimb'] / 1e6:+,.1f}m")
print(f"  BETE reimbursement change:      ${pkg.state['bete'] / 1e6:+,.1f}m")
print(f"  Fairness Credit change:         ${pkg.ptfc_cost(p) / 1e6:+,.1f}m")

# Towns: the mill-rate change in each municipality, and the statewide average
# on the measure the Explorer reports (ptfc_takeup.levy_weighted)
t = pkg.towns.assign(mill_change=pkg.towns["mill_delta"] * 1000)
pct = pd.Series((t["mill_delta"] / (t["mill"] - t["mill_delta"])).to_numpy(),
                index=T._key(t["Place"]).to_numpy())
print(f"Average mill change: {100 * T.levy_weighted(pct):+.2f}%; "
      f"{(t['mill_change'] > 0).sum()} of {len(t)} towns rise")
print(t.nlargest(3, "mill_change")[["Place", "mill_change"]].to_string(index=False))

# Households: expected net gain (lower bill plus extra credit), all households
gain = pkg.vec()
print(f"Net gain to Maine households: ${(gain * m.W).sum() / 1e6:,.1f}m; "
      f"average ${np.average(gain, weights=m.W):,.0f}")

# pkg.town_file = "my_package_towns.csv"; pkg.write_towns()   # town table to data/derived/scenarios/
```

With the data in this repository it prints:

```
Revenue Sharing I cut:            $66.8m
  homestead reimbursement change: $+54.2m
  BETE reimbursement change:      $+1.7m
  Fairness Credit change:         $+10.9m
Average mill change: +2.24%; 491 of 494 towns rise
           Place  mill_change
EAST MILLINOCKET     2.441288
          MEXICO     2.341330
       VAN BUREN     2.068925
Net gain to Maine households: $39.8m; average $67
```

The three cost lines add up to the cut. The homestead reimbursement rises
because the exemption is larger; it and the BETE reimbursement also rise with
each town's mill rate, which the cut pushes up. Each
household's gain is its lower bill (if it holds a homestead) plus its extra
credit, less what the higher mill rate adds to its bill. Owners are counted
partly as homesteaders and partly not, at their area's homestead rate, because
the Census sample does not record who holds the exemption. The decile code from
Example 1 works here with `gain = pkg.vec()`.

How `Combo` works, and the assumptions behind it, are set out at the top of
`model/task_force.py`. To use the Scenario 19 two-tier credit instead, pass a
`TF.TwoTierParams` as `p`. With `revi_cut=0` and `p = m.p0`, `Combo` prices an
exemption or reimbursement change on its own; for the exemptions of Scenarios 1
to 3 its net cost is within $0.8m of step 03's, which estimates the credit
displaced by the exemption slightly differently.

## Example 3: see your scenario in the Explorer

To look at a scenario with the same pages, charts and tables as the published
Relief Explorer, list it in `model/local_scenarios.py` and rebuild. The file
takes the same two kinds of scenario as Examples 1 and 2:

```python
SCENARIOS = [
    CreditChange("20", "Raise the 65+ maximum credit to $2,500", {"cap_senior": 2_500.0}),
    Package("21", "Exemption $40,000 at 76%, maximum credits $2,250 and $3,000",
            exemption=40_000.0, reimbursement=0.76,
            credit={"cap_under65": 2_250.0, "cap_senior": 3_000.0}),
]
```

Then run `make` (on Windows, `python pipeline/06_build_dashboard_data.py` and
then `python pipeline/08_build_explorer.py`, which take about half a minute)
and open `output/explorer.html` in a browser. The two scenarios appear on every
page in a fourth group, "Scenarios added locally": in the scenario table and
charts, by income decile and survey area, in the burden counts, the town
mill-rate changes (for a package), each archetype's results, the worked
examples and the commercial properties. Their figures match Examples 1 and 2:
S20 costs $5.6m; S21 needs a $66.8m Revenue Sharing I cut and delivers $39.8m.

- **`CreditChange(id, name, changes)`** changes Fairness Credit parameters
  (`Params` fields) and leaves everything else as today. Its State cost is
  whatever the change costs.
- **`Package(id, name, exemption, reimbursement, credit={}, revi_cut=None)`**
  sets the homestead exemption and reimbursement rate, with any credit changes
  in `credit`, paid for by cutting Revenue Sharing I. With `revi_cut=None` the
  cut is solved so the State's net cost is zero, as in S15 to S19, and the step
  stops with a message if even abolishing Revenue Sharing I would not pay for
  it. Give `revi_cut` a dollar figure to fix the cut instead; `revi_cut=0`
  prices an exemption or reimbursement change on its own.
- Ids are whole numbers above 19. The written descriptions on the page come
  from the published Explorer, so a local scenario gets a short one built from
  its name and parameters, and a banner on every page says the build is local.
- The scenarios also go into `output/dashboard.json`. Empty the list again
  before producing files for publication.

Other kinds of scenario (a liability ceiling like S7 and S8, or a reallocation
like S9 to S13) need code in `load()` in `model/bundle_scenarios.py`, where the
published ones are built, and in `model/bundle_geography.py` if they change mill
rates. The local Explorer shows anything that reaches `output/dashboard.json`.
