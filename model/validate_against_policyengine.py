"""
Household-by-household validation of ptfc_engine against policyengine_us.

Draws a stratified sample of PUMS households, runs each through PolicyEngine's
`me_property_tax_fairness_credit` in household mode, and compares the result
with `ptfc_engine.credit` under TY2025 law. Any mismatch is either an engine bug
or a different reading of the statute.

Run from the repository root, after the pipeline has written the PUMS extract:

    pip install policyengine-us
    python3 model/validate_against_policyengine.py

Writes the sample with both credits to data/derived/pe_validation.csv.
"""
import sys

import numpy as np
from policyengine_us import Simulation

import paths
import ptfc_engine as E
import ptfc_takeup as T

YR = 2025
N = 250
rng = np.random.default_rng(20260908)

df = T.load_pums()

# stratify so the sample hits every branch of the formula
strata = {
    "senior_owner":   df.senior & df.owner & (df.prop_tax > 0),
    "under65_owner":  ~df.senior & df.owner & (df.prop_tax > 0),
    "renter":         df.renter & (df.rent_annual > 0),
    "married_deps":   df.married & (df.n_dep >= 2),
    "single_dep1":    ~df.married & (df.n_dep == 1),
    "zero_credit":    df.income > 120_000,
    "low_income":     df.income < 15_000,
}
idx = []
for name, m in strata.items():
    pool = df.index[m.fillna(False)]
    if len(pool):
        idx.extend(rng.choice(pool, size=min(N // len(strata) + 1, len(pool)),
                              replace=False))
sample = df.loc[sorted(set(idx))].copy()
print(f"validating {len(sample)} households", file=sys.stderr)


def pe_credit(row):
    """One household through PolicyEngine. Members: head, optional spouse,
    n_dep children. All income is loaded onto the head as employment income;
    its composition does not affect the PTFC, whose income definition adds
    Social Security back in full. Rent is the counted rent the engine uses."""
    people = {"head": {"age": {YR: int(row.age_head)},
                       "employment_income": {YR: float(max(row.income, 0))},
                       "real_estate_taxes": {YR: float(row.prop_tax)},
                       "rent": {YR: float(np.nan_to_num(row.rent_counted))}}}
    members = ["head"]
    if row.married and row.age_spouse >= 0:
        people["spouse"] = {"age": {YR: int(row.age_spouse)},
                            "employment_income": {YR: 0.0}}
        members.append("spouse")
    for i in range(int(row.n_dep)):
        people[f"kid{i}"] = {"age": {YR: 8}, "employment_income": {YR: 0.0}}
        members.append(f"kid{i}")

    marital = {"m": {"members": ["head", "spouse"]}} if "spouse" in people \
        else {"m": {"members": ["head"]}}
    sit = {
        "people": people,
        "tax_units": {"tu": {"members": members}},
        "families": {"f": {"members": members}},
        "spm_units": {"s": {"members": members}},
        "marital_units": marital,
        "households": {"h": {"members": members,
                             "state_name": {YR: "ME"},
                             "tenure_type": {YR: "OWNED_OUTRIGHT" if row.owner
                                             else "RENTED"}}},
    }
    s = Simulation(situation=sit)
    return float(s.calculate("me_property_tax_fairness_credit", YR).sum())


mine = E.credit(sample, E.BASELINE)
rows = []
for i, (_, row) in enumerate(sample.iterrows()):
    try:
        pe = pe_credit(row)
    except Exception as exc:                                  # noqa: BLE001
        pe = float("nan")
        print(f"  [{i}] PE error: {exc}", file=sys.stderr)
    rows.append(pe)
    if i % 25 == 0:
        print(f"  {i}/{len(sample)}", file=sys.stderr)

sample["mine"] = mine
sample["pe"] = rows
sample["diff"] = sample["mine"] - sample["pe"]
ok = sample["diff"].abs() < 0.51
print(f"\nMATCH: {ok.sum()}/{len(sample)}  "
      f"({100*ok.mean():.1f}%)   max |diff| = ${sample['diff'].abs().max():,.2f}")
bad = sample.loc[~ok, ["age_head", "age_spouse", "married", "n_dep", "owner",
                       "renter", "income", "prop_tax", "rent_counted",
                       "mine", "pe", "diff"]]
if len(bad):
    print("\nMISMATCHES:")
    print(bad.head(25).to_string())
sample.to_csv(paths.DERIVED / "pe_validation.csv", index=False)
