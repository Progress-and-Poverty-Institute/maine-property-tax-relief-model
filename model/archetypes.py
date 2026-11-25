"""Household archetypes, built on the PUMS tax-unit extract.

Archetypes are defined on `pums_taxunits.csv`, the same population the scenario
engine uses, so a household can be traced from an archetype straight into a
scenario result.

There are two sets, with opposite design criteria, and they are reported as two
separate tables:

- **Broad categories** (`broad()`) describe the ordinary experience of Maine
  households so the Task Force can see where each relief program lands. They
  tile the population exactly, are tenure-pure, and use as few cuts as possible.
- **Narrow archetypes** (`narrow_rules()`) describe the households the relief
  system leaves burdened. They partition the households whose property tax is
  still above 6% of income after the PTFC.

The burden measure (`net_burden()`):

    net burden = (counted property tax - PTFC credit) / household income

- Counted property tax is the owner's actual bill, or 15% of annual rent for
  renters, per 36 M.R.S. 5219-KK. Rent is the occupancy portion only (see
  `congregate_care.py`).
- The homestead exemption is already inside the owner's reported bill, because
  PUMS reports what the household pays.
- The PTFC credit is current law, assumed claimed in full. Full claiming
  measures the burden the program's design leaves; expected receipt (credit x
  take-up) measures what households actually experience.

Caveats on the inputs:

- `prop_tax` is a binned, self-reported midpoint. Totals are sound;
  individual placement near a threshold is not.
- Renter rent is ACS contract rent (RNTP), not gross rent, because MRS Rule 813
  counts only rent paid solely for the right of occupancy. Utilities or
  services included in a landlord's charge can still overstate a renter's
  counted tax; congregate-care fees are adjusted in `congregate_care.py`.
- Characteristics derived from WAGP/SEMP/SSP etc. describe the householder, not
  the household. The extract has `age_spouse` but no spouse income.
- Households with income <= 0 (about 1% of Maine) are excluded from any burden
  ranking because the ratio is undefined. Most are PTFC-eligible, so they are
  excluded as unmeasurable, not as comfortable.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import congregate_care as CC  # noqa: E402

# Regional typology from Ward clustering of the ten PUMAs on nine variables
# (median income, median owner home value, ownership rate, self-employment
# rate, share 65+, share of population in towns under 2,000 and over 10,000,
# full-value mill rate, PTFC take-up). The midcoast (500) sorts with Rural, not
# with the coastal south: 41% of its population is in towns under 2,000 and
# none in towns over 10,000.
REGIONS = {100: "Rural", 200: "Rural", 500: "Rural",
           300: "Service", 400: "Service", 600: "Service",
           700: "South", 800: "South", 900: "South",
           1000: "Portland"}

RENT_SHARE = 0.15          # 36 M.R.S. 5219-KK
INCOME_FLOOR = 45_000.0    # broad-category cut; tuned, no statutory basis
SENIOR_AGE = 65            # statutory: senior benefit base and cap


def counted_tax(df, rent_share=RENT_SHARE):
    """Owners' actual bills plus the statutory rent constituting property tax."""
    own = df["owner"].to_numpy()
    ren = df["renter"].to_numpy()
    tax = df["prop_tax"].to_numpy()
    # Occupancy rent, not the reported fee. See congregate_care.py.
    rent = CC.rent_for_credit(df)
    return (np.where(own, tax, 0.0)
            + rent_share * np.where(ren, rent, 0.0))


def net_burden(df, credit, rent_share=RENT_SHARE):
    """Counted tax net of the PTFC, as a share of household income.

    `credit` is the per-household current-law credit (ptfc_engine.credit, or
    ptfc_recalibrate.Model.base). Pass credit * tau for the expected-receipt
    variant. Undefined where income <= 0; returns NaN there.
    """
    inc = df["income"].to_numpy()
    crpt = counted_tax(df, rent_share)
    return np.where(inc > 0,
                    (crpt - np.asarray(credit, float)) / np.maximum(inc, 1),
                    np.nan)


BURDEN_THRESHOLD = 0.06      # fixed, not a percentile -- see burdened()


def above(burden, threshold=BURDEN_THRESHOLD):
    """Households whose burden is above `threshold`, ignoring floating-point noise.

    Burdens are compared after rounding to nine decimal places, as the burden
    bins are. The liability ceilings in Scenarios 7 and 8 bring many households
    to exactly 6% of income, and unrounded, the last bit of arithmetic, which
    differs between computers, decided which side of the line each one fell.
    Nine decimals is far below any real difference in burden and far above
    double-precision error.
    """
    b = np.asarray(burden, float)
    return np.isfinite(b) & (np.round(b, 9) > threshold)


def burdened(df, credit, threshold=BURDEN_THRESHOLD):
    """Boolean mask for households above `threshold` of income after all relief.

    This is the definition the narrow archetypes use.

    The threshold is a fixed 6% of income, not a percentile. A percentile would
    redefine the group whenever the input data is revised; a fixed line holds
    the definition still and lets the group size move instead, so a change in
    the count is a finding rather than a moved line.

    Six per cent is the threshold the PTFC used before 2020, and the ceiling
    rate in Scenarios 7 and 8, so the archetypes and the scenarios are measured
    against the same line.

    Returns (mask, threshold).
    """
    return above(net_burden(df, credit), threshold), float(threshold)


# --------------------------------------------------------------- broad set
def broad(df, income_floor=INCOME_FLOOR, senior_age=SENIOR_AGE):
    """Six mutually exclusive categories covering 100% of Maine households.

    The categories come from weighted k-prototypes clustering on age, log
    income, household size, years in place and region, run separately for
    owners and renters so tenure cannot leak, then converted to exact rules.
    The rules reproduce the cluster assignment 81.2% of the time and, unlike
    the clusters, are reproducible from the definition alone. Owner rows sum to
    100% of owners and renter rows to 100% of renters.

    Two parameters:
    - `income_floor` ($45,000) has no statutory basis. It was chosen from the
      clustering; B4 remains clearly the most burdened category anywhere from
      $35,000 to $55,000.
    - the age cut at 65 is statutory, matching the senior benefit base and cap,
      and applies to both owners and renters because the senior base and cap
      apply to both. It separates delivered relief between B2 and B3 far more
      sharply than a 20-year tenure cut does, and gives B3 a narrower age
      range. Tenure remains a descriptive attribute of each category rather
      than part of its definition.

    `n_dep` is used rather than household size because it is the variable the
    PTFC benefit base keys on. Its PUMS derivation follows the statutory test:
    RELSHIPP 25/26/27/28/30/35 under 19, or under 24 for a student.
    """
    own = df["owner"].to_numpy()
    ren = df["renter"].to_numpy()
    age = df["age_head"].to_numpy()
    inc = df["income"].to_numpy()
    nd = df["n_dep"].to_numpy()
    b = {}
    b["B1 Family household with dependents"] = own & (nd >= 1)
    b["B2 Older owner, no dependents"] = own & (nd == 0) & (age >= senior_age) \
        & (inc >= income_floor)
    b["B3 Working-age owner, no dependents"] = own & (nd == 0) & (age < senior_age) \
        & (inc >= income_floor)
    b["B4 Lower-income owner, no dependents"] = own & (nd == 0) & (inc < income_floor)
    b["B5 Renter under 65"] = ren & (age < senior_age)
    b["B6 Renter 65 and over"] = ren & (age >= senior_age)
    return b


# -------------------------------------------------------------- narrow set
def narrow_notes(df, masks, credit) -> dict:
    """A prose note for each narrow archetype: what the group is and why it
    matters. Every figure in the text is computed here from the same data as
    `profile()`, so the notes cannot drift from the numbers beside them when
    the data change."""
    p = profile(df, masks, credit, order=list(masks))
    p.index = [a.split()[0] for a in p["archetype"]]
    W = df["WGTP"].to_numpy().astype(float)
    mk = {k.split()[0]: np.asarray(v, bool) for k, v in masks.items()}

    def share(cond, group):
        return float(W[group & cond].sum() / W[group].sum())

    pct = lambda x: f"{100 * x:.0f}%"
    pct1 = lambda x: f"{100 * x:.1f}%"
    n1, n2, n4, n5, n6, n7 = (p.loc[k] for k in ("N1", "N2", "N4", "N5", "N6", "N7"))
    # ACS move-in codes 1 to 3: moved in within the last four years.
    recent = pd.to_numeric(df["MV"], errors="coerce").to_numpy() <= 3
    rent_over_income = df["rent_annual"].to_numpy() > df["income"].to_numpy()
    return {
        "N1": f"The most burdened group in the set: {pct1(n1.burden_pre)} of income "
              "before any credit, ahead of every other archetype. Older owners "
              "living alone, long settled. Almost all are PTFC-eligible, the median "
              "one already draws the senior maximum, and they are STILL above the 6% "
              "line after claiming it. The credit is working and the burden remains. "
              f"{pct(n1.pct_at_cap)} sit at the cap, so they gain only if the maximum "
              "rises; the benefit base does almost nothing for them.",
        "N2": f"The same age profile as N1 on {n2.med_income / n1.med_income:.1f}x the "
              f"income (${n2.med_income:,.0f} against ${n1.med_income:,.0f}), and a "
              f"burden {100 * (n1.burden_pre - n2.burden_pre):.1f} points lighter. "
              f"{pct(n2.pct_at_cap)} sit at the cap, against {pct(n1.pct_at_cap)} in N1, "
              "so the benefit base does as much work here as the maximum credit. The "
              "contrast with N1 is the "
              "clearest evidence in the set that what drives burden among older "
              "owners is living alone rather than age.",
        "N3": "Working-age owner living alone. Too young for the senior benefit base "
              "or the senior cap, and no dependent uplift. Lower income than N4 on a "
              "markedly cheaper house, which is why its burden is worse. Age, not "
              "wealth, is what separates it from N1.",
        "N4": "Working-age owner living with a partner, no dependents. Among the "
              "higher-income owner archetypes, so fewer of them qualify, and the "
              "mildest burden of the owner set. Present because the burdened group "
              "is not only the old and the poor. Base-bound rather than cap-bound: "
              f"{pct(n4.pct_at_cap)} at the cap against {pct(n5.pct_at_cap)} for N5, "
              "which is why the two are kept apart despite similar burdens.",
        "N5": "Owner with children or other dependents at home. The newest to their "
              "homes of any owner archetype: the median moved in 5-9 years ago and "
              f"{pct(share(recent, mk['N5']))} within the last four years. The "
              "dependent test runs BEFORE the value test, so a family with children "
              "in a $2,000,000 house is N5 rather than N6. Its dependents lift the "
              "benefit base, which is why its post-credit burden lands below N1's "
              "despite a much larger bill.",
        "N6": "Owner of a high-value home. The largest bills of any archetype and the "
              "smallest share eligible, because income disqualifies about half. The "
              "only archetype whose burden barely moves after the credit, "
              f"{pct1(n6.burden_pre)} to {pct1(n6.burden_post)}: the cap binds long "
              "before the bill does. Both the case for a liability ceiling and the "
              "case against it.",
        "N7": "All burdened renters. The youngest, poorest and most recently moved of "
              f"any group here, nearly all eligible ({pct(n7.pct_eligible)}), and the "
              "credit does more work here than anywhere else, cutting the burden "
              "roughly in half. TWO CAUTIONS. A renter's 'tax' is the statutory 15% "
              f"of rent, a proxy rather than a bill anyone receives. And "
              f"{pct(share(rent_over_income, mk['N7']))} of this group reports annual "
              "rent exceeding annual income, which is not a sustainable budget and "
              "means cash income understates their resources; the "
              f"{pct1(n7.burden_pre)} burden is indicative rather than comparable "
              "with an owner's.",
    }


# Seven groups. Older owners without dependents are split on whether the
# householder lives alone: on the 2020-2024 data the halves differ by 7.7 points
# of pre-credit burden (19.6% against 12.0%), by 16 points of eligibility and by
# 31 points on the share at the maximum credit, so they respond to different
# levers. MRS's
# Penobscot income-tax match points the same way from different data: single
# filers rise from 21% of the least burdened to 67% of the 90th-95th percentile
# band.
#
# Renters form one group; renters 65 and over are too few in the burdened
# group to describe separately.
#
# Childless working-age couples and owners with children are kept apart despite
# similar burdens (9.9% against 10.3%). They differ by 16 points on the share at
# the cap, so one is base-bound and the other cap-bound.
NARROW_ORDER = ["N1 Older owner, lives alone",
                "N2 Older owner, lives with others",
                "N3 Working-age owner, lives alone",
                "N4 Working-age owner, lives with a partner",
                "N5 Owner with children at home",
                "N6 Owner of a high-value home",
                "N7 Renter"]


def narrow_rules(df, credit, threshold=BURDEN_THRESHOLD):
    """The seven narrow archetypes as closed-form rules.

    They partition the burdened group exactly (see `burdened()`): seven named
    archetypes, no overlap, no remainder. `n_dep >= 1` is tested before home
    value, so a family with children in a $2,000,000 house is N5 rather than
    N6. The rules were fitted to a k-prototypes clustering of the burdened
    group on age, log income, household size, years in place and home value.

    Returns (masks, cutoff).
    """
    top, cut = burdened(df, credit, threshold)
    own = df["owner"].to_numpy()
    ren = df["renter"].to_numpy()
    age = df["age_head"].to_numpy()
    nd = df["n_dep"].to_numpy()
    val = pd.to_numeric(df["home_value"], errors="coerce").fillna(0).to_numpy()
    alone = np.isin(df["HHT"].to_numpy(), (4, 6))   # HHT 4/6: householder alone

    o = top & own
    dep = o & (nd >= 1)
    rest = o & (nd == 0)
    rich = rest & (val >= 1_000_000)
    plain = rest & (val < 1_000_000)
    out = {
        NARROW_ORDER[0]: plain & (age >= SENIOR_AGE) & alone,
        NARROW_ORDER[1]: plain & (age >= SENIOR_AGE) & ~alone,
        NARROW_ORDER[2]: plain & (age < SENIOR_AGE) & alone,
        NARROW_ORDER[3]: plain & (age < SENIOR_AGE) & ~alone,
        NARROW_ORDER[4]: dep,
        NARROW_ORDER[5]: rich,
        NARROW_ORDER[6]: top & ren,
    }
    covered = np.zeros(len(df), bool)
    for v in out.values():
        assert not (covered & v).any(), "narrow archetypes overlap"
        covered |= v
    assert (covered == top).all(), "narrow archetypes do not tile the burdened group"
    return out, cut


def _wmedian(x, w):
    """Weighted median, ignoring non-finite x."""
    x = np.asarray(x, float); w = np.asarray(w, float)
    ok = np.isfinite(x) & (w > 0)
    if not ok.any():
        return float("nan")
    x, w = x[ok], w[ok]
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w) / w.sum()
    return float(x[np.searchsorted(c, 0.5)])


def profile(df, masks, credit, tau=None, order=None):
    """The published archetype columns for any mask set, computed from the model.

    `credit` is the full-entitlement current-law credit (Model.base). `tau` is
    per-household take-up; delivered relief is credit x tau x weight, and is
    omitted when tau is None. `share_of_base` is a share of owners or of
    renters, whichever the group mostly is. Burden pre and post are medians of
    separately sorted distributions, so the gap between them is the group
    median moving, not any household's own change.
    """
    W = df["WGTP"].to_numpy().astype(float)
    own, ren = df["owner"].to_numpy(), df["renter"].to_numpy()
    credit = np.asarray(credit, float)
    inc = df["income"].to_numpy()
    crpt = counted_tax(df)
    pre = np.where(inc > 0, crpt / np.maximum(inc, 1), np.nan)
    post = net_burden(df, credit)
    val = pd.to_numeric(df["home_value"], errors="coerce").to_numpy()
    rent = np.nan_to_num(df["rent_annual"].to_numpy())
    age = df["age_head"].to_numpy()
    # Which constraint is binding, among households the credit actually pays.
    # `cap` is the maximum credit; `base` is the benefit base, which limits how
    # much property tax the formula will count in the first place.
    from ptfc_engine import TY2026 as _P
    senior = df["senior"].to_numpy()
    cap = np.where(senior, _P.cap_senior, _P.cap_under65)
    at_cap = (credit > 0) & (credit >= cap - 0.5)
    at_base = (credit > 0) & ~at_cap & (crpt >= _base_for(df, _P) - 0.5)
    rows = []
    for k in (order or masks):
        m = masks[k]
        if not m.any():
            den = W.sum()
        elif W[m & own].sum() >= W[m & ren].sum():
            den = W[own].sum()
        else:
            den = W[ren].sum()
        owner_group = W[m & own].sum() >= W[m & ren].sum()
        r = dict(archetype=k, households=float(W[m].sum()), n=int(m.sum()),
                 share_of_base=float(W[m].sum() / den),
                 base_is="owners" if owner_group else "renters",
                 med_age=_wmedian(age[m], W[m]),
                 med_income=_wmedian(inc[m], W[m]),
                 med_home=_wmedian((val if owner_group else rent)[m], W[m]),
                 med_tax=_wmedian(crpt[m], W[m]),
                 burden_pre=_wmedian(pre[m], W[m]),
                 burden_post=_wmedian(post[m], W[m]),
                 pct_eligible=float(W[m & (credit > 0)].sum() / W[m].sum()),
                 med_credit=_wmedian(credit[m & (credit > 0)], W[m & (credit > 0)]),
                 pct_at_cap=float(W[m & at_cap].sum() / max(W[m & (credit > 0)].sum(), 1)),
                 pct_at_base=float(W[m & at_base].sum() / max(W[m & (credit > 0)].sum(), 1)))
        if tau is not None:
            r["delivered"] = float((credit * np.asarray(tau, float) * W)[m].sum())
        rows.append(r)
    return pd.DataFrame(rows)


def _base_for(df, p):
    """Per-household benefit base under `p`, for the at-base test in profile()."""
    senior = df["senior"].to_numpy()
    nd = df["n_dep"].to_numpy()
    married = df["married"].to_numpy()
    b = np.where(nd >= 2, p.base_joint_multi,
                 np.where((nd == 1) | married, p.base_hoh_one, p.base_single))
    return np.where(senior, np.maximum(b, p.base_senior), b)


# The rules, as text, so the published tables carry their own definition.
BROAD_LOGIC = {
    "B1": "TEN in (1,2) AND n_dep >= 1",
    "B2": "TEN in (1,2) AND n_dep = 0 AND AGEP >= 65 AND income >= 45000",
    "B3": "TEN in (1,2) AND n_dep = 0 AND AGEP < 65 AND income >= 45000",
    "B4": "TEN in (1,2) AND n_dep = 0 AND income < 45000",
    "B5": "TEN in (3,4) AND AGEP < 65",
    "B6": "TEN in (3,4) AND AGEP >= 65",
}
NARROW_LOGIC = {
    "N1": "TEN in (1,2) AND n_dep = 0 AND home_value < 1000000 "
          "AND AGEP >= 65 AND HHT in (4,6)",
    "N2": "... AND AGEP >= 65 AND HHT not in (4,6)",
    "N3": "... AND AGEP < 65 AND HHT in (4,6)",
    "N4": "... AND AGEP < 65 AND HHT not in (4,6)",
    "N5": "TEN in (1,2) AND n_dep >= 1",
    "N6": "TEN in (1,2) AND n_dep = 0 AND home_value >= 1000000",
    "N7": "TEN in (3,4)",
}
