"""Property Tax Fairness Credit (PTFC) take-up by PUMA, and the homestead
geography the scenario model needs.

Take-up is MRS claimants divided by eligible households. PUMA is the only Maine
geography where income and property tax are observed on the same household
(ACS PUMS), so eligibility is counted directly from that joint distribution and
needs no assumption that households within an area are alike. The joint matters:
shuffling tax and rent across households within each PUMA, which keeps both
marginal distributions and destroys the association, inflates the eligible
count by 7.9% statewide (0.4% to 13.0% by PUMA).

GEOGRAPHY. data/raw/xwalk_muni_to_puma.csv assigns each of Maine's 494
municipalities and unorganised territories wholly to one of the ten 2020 PUMAs,
from a boundary overlay. Implied persons per household by PUMA runs 2.13 to
2.37 against a statewide 2.28, with Portland lowest. Two unorganised
territories straddle a PUMA line (SOMERSET UT, pop 767, mostly PUMA 200;
PENOBSCOT UT, pop 1,676, mostly PUMA 100). This is immaterial: MRS reports UT
claimants in per-county "Unorganized Territory" rows totalling 320 claimants
statewide (0.24%), and each county's row maps to a single PUMA.

VINTAGE. The MRS claimant file is for TY2024, but eligibility is scored under
TY2025 law (ptfc_engine.BASELINE), a year later. The eligible count depends on
the law year, because the benefit bases are indexed each year while each
household's income, tax and rent stay at their survey values: 193,935
households are eligible under TY2024 law, 196,956 under TY2025 and 198,876
under TY2026. Matching the years (TY2024) would raise statewide take-up from
68.2% to 69.2%, and every take-up-weighted dollar figure by 1.6%. This release
keeps the TY2025 basis and the Technical Report states the effect;
pipeline/07_validate.py uses the matched TY2024 basis.
"""
from functools import lru_cache

import numpy as np
import pandas as pd

import paths
import ptfc_engine as E  # noqa: E402
import congregate_care as CC  # noqa: E402

PUMS_PATH = paths.PUMS
PTFC_TOWN_PATH = paths.PTFC_BY_TOWN
XWALK_PATH = paths.XWALK_MUNI_PUMA

# Short labels for the ten 2020 PUMAs, ordered rural -> urban.
PUMA_LABEL = {
    100:  "Aroostook, Washington & N. Penobscot",
    200:  "Oxford, Somerset, Franklin & Piscataquis",
    500:  "Hancock, Knox, Waldo & Lincoln",
    300:  "S. Penobscot (Bangor)",
    400:  "Kennebec (Augusta, Waterville)",
    600:  "Androscoggin (Lewiston, Auburn)",
    700:  "Sagadahoc & N. Cumberland",
    800:  "York (West) & Cumberland (West)",
    900:  "Cumberland (ex-Portland) & York (East)",
    1000: "Portland, S. Portland & Westbrook",
}
PUMA_ORDER = [100, 200, 500, 300, 400, 600, 700, 800, 900, 1000]

# Approximate Maine filing thresholds in 2024 dollars (standard deduction).
# Used only to DESCRIBE the eligible population, never to score eligibility.
FILING_THRESHOLD = {"single": 14_600.0, "married": 29_200.0}


# --------------------------------------------------------------------- load
def load_pums() -> pd.DataFrame:
    """The ACS PUMS 2020-2024 Maine extract, one row per household.

    Adds `rent_counted`: the portion of reported rent that counts toward the
    credit and the burden. For all but a few hundred households it equals
    `rent_annual`; where the reported rent is a congregate-care fee it is the
    occupancy portion that MRS Rule 813 allows. `rent_annual` keeps the fee and
    is what published rent figures report. This is the ONLY place the column is
    created, so everything downstream of the extract inherits it; read it
    through congregate_care.rent_for_credit, never by name.
    """
    d = pd.read_csv(PUMS_PATH)
    d["rent_counted"] = CC.counted_rent(d)
    return d


def load_xwalk() -> pd.DataFrame:
    """Municipality -> PUMA, with a population-share allocation weight.

    In the current crosswalk every municipality sits wholly in one PUMA, so
    every weight is 1.0. The weight exists so that a municipality straddling a
    PUMA line can be split simply by adding a second row for it with the
    population of each piece; allocation then follows automatically.

    The two unorganised territories that straddle a line (SOMERSET UT and
    PENOBSCOT UT) are assigned whole. Splitting one is a data edit, not a code
    change.
    """
    x = pd.read_csv(XWALK_PATH)
    x["key"] = x["MUNI"].astype(str).str.upper().str.strip()
    x["county"] = x["County"].astype(str).str.upper().str.strip()
    x["weight"] = _share_within(x, "key", "pop2020")
    return x


def _share_within(df: pd.DataFrame, group: str, size: str) -> pd.Series:
    """Each row's share of its group's total `size`.

    Falls back to an equal split where a whole group has zero population, so a
    zero-population territory can never produce a divide-by-zero.
    """
    tot = df.groupby(group)[size].transform("sum")
    n = df.groupby(group)[size].transform("size")
    return np.where(tot > 0, df[size] / tot.replace(0, np.nan), 1.0 / n)


# The MRS file withholds any town with fewer than ten PTFC returns and reports
# them as one unnamed row. SUPPRESSED_CAP is the most any one of those towns can
# therefore hold. See `suppressed_allocation`.
SUPPRESSED_LABEL = "LESS THAN 10 PTFC RETURNS IN TOWN"
SUPPRESSED_CAP = 9.0


def _raw_ptfc_town() -> pd.DataFrame:
    """The MRS workbook as filed, including the three rows with no town."""
    d = pd.read_excel(PTFC_TOWN_PATH, skiprows=2, engine="openpyxl")
    d.columns = ["town", "county", "n_ptfc", "amt_ptfc"]
    for c in ("n_ptfc", "amt_ptfc"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["county"] = (d["county"].astype(str).str.upper()
                   .str.replace(r"\s*COUNTY\s*$", "", regex=True).str.strip())
    return d


def suppressed_allocation(raw: pd.DataFrame) -> pd.DataFrame:
    """The withheld small-town claimants, placed in the towns they must be in.

    MRS reports claimants by town but withholds any town with fewer than ten
    returns, collecting them into a single unnamed row: 297 claimants and
    $215,767 in TY2024. Leaving that row out would drop those claimants from the
    take-up numerators while the PUMS denominator still counts their households,
    understating take-up where it is lowest.

    Three groups are missing from the claimant count: these 297, the 1,587 with
    out-of-state mailing addresses, and the 3,377 TY2024 returns filed or
    amended after the 14 November 2025 extract. This is the smallest, but the
    only one that can be placed geographically, so the only one that changes
    the shape of the take-up vector rather than its level. It lands almost
    entirely in the two lowest take-up areas: Aroostook/Washington/N. Penobscot
    rises 0.98 points and Oxford/Somerset/Franklin/Piscataquis 0.47. Every
    other area moves less than 0.07.

    THE RULE. The withheld towns are exactly those in the crosswalk that the MRS
    file never names: 60 municipalities, 6,370 people, 0.47% of the state. The
    297 are distributed across them in proportion to 2020 population, then capped
    at SUPPRESSED_CAP, because a town holding ten or more would not have been
    withheld in the first place. The cap binds: a straight population split gives
    five towns more than nine, and after redistribution eight sit at the cap. The
    credit is allocated pro rata to the claimants so both totals are preserved
    exactly.

    THE ASSUMPTION. Population-proportional allocation is an estimate, not a
    measurement, and the eight capped towns are mechanical rather than
    estimated. It is consistent with the data: the withheld rows average
    $726.49 a claimant, the model assigns them roughly $755 from their areas,
    and adding them to both sides of the credit validation moves the gap from
    +1.36% to +1.37%.

    Any comparison against MRS's named-town subtotal ($113,102,190) excludes
    these claimants, so it must exclude them from the model side too.
    """
    xwalk = load_xwalk()

    row = raw[raw["county"].astype(str).str.upper().str.strip() == SUPPRESSED_LABEL]
    if row.empty:
        return pd.DataFrame(columns=["town", "county", "n_ptfc", "amt_ptfc", "key"])
    n_total = float(row["n_ptfc"].sum())
    amt_total = float(row["amt_ptfc"].sum())

    named = set(raw.loc[raw["town"].notna(), "town"]
                .astype(str).str.upper().str.strip())
    muni = xwalk[xwalk["MuniOrUT"] == "m"].drop_duplicates(subset=["key"])
    miss = muni[~muni["key"].isin(named)].copy()
    if miss.empty:
        raise ValueError("no towns missing from the MRS file; the suppressed "
                         "row has nowhere to go")

    w = miss["pop2020"].astype(float).to_numpy()
    alloc = np.zeros(len(w))
    free = np.ones(len(w), bool)
    remaining = n_total
    for _ in range(50):                       # cap, redistribute, repeat
        if not free.any() or remaining <= 1e-9:
            break
        denom = (w * free).sum()
        if denom <= 0:
            alloc[free] += remaining / free.sum()
            break
        add = remaining * w * free / denom
        over = (alloc + add) > SUPPRESSED_CAP
        if over.any():
            alloc[over] = SUPPRESSED_CAP
            free = free & ~over
            remaining = n_total - alloc.sum()
        else:
            alloc = alloc + add
            remaining = 0.0
    if not np.isclose(alloc.sum(), n_total, rtol=1e-9):
        raise ValueError(f"allocated {alloc.sum():,.2f} of {n_total:,.0f} "
                         "suppressed claimants; the cap cannot absorb them")

    out = pd.DataFrame({
        "town": miss["MUNI"].to_numpy(),
        "county": miss["county"].to_numpy(),
        "n_ptfc": alloc,
        "amt_ptfc": alloc / n_total * amt_total,
        "key": miss["key"].to_numpy(),
    })
    return out[out["n_ptfc"] > 0].reset_index(drop=True)


def mrs_file_totals() -> dict:
    """Statewide PTFC claimants and credit that the take-up table must sum to.

    The file's grand total less the returns that cannot be placed in Maine (the
    out-of-state mailing addresses and the unassigned towns), which is the named
    towns plus the withheld small-town row: 134,245 claimants and $113,317,957
    in the TY2024 file. Raises if the rows do not add up to the grand total,
    which would mean the file's layout has changed.
    """
    raw = _raw_ptfc_town()
    no_town = raw["town"].isna()
    is_grand = no_town & (raw["county"].isna() | raw["county"].isin(["NAN", "NONE", ""]))
    if is_grand.sum() != 1:
        raise ValueError("PTFC by-town file: expected one grand-total row")
    grand = raw[is_grand].iloc[0]
    rows = raw[~is_grand]
    for c in ("n_ptfc", "amt_ptfc"):
        if abs(rows[c].sum() - grand[c]) > 0.5:
            raise ValueError(f"PTFC by-town file: rows do not sum to the grand total ({c})")
    placed = rows[~no_town[~is_grand] | (rows["county"] == SUPPRESSED_LABEL)]
    return dict(claimants=float(placed["n_ptfc"].sum()), credit=float(placed["amt_ptfc"].sum()))


def load_ptfc_town() -> pd.DataFrame:
    """MRS Form 1040ME returns claiming a PTFC, by town, TY2024.

    Caveat carried in the source file: the town is taken from the MAILING
    ADDRESS on the 1040 and may differ from the property location.

    The withheld small-town claimants are imputed back into the towns they must
    belong to (see `suppressed_allocation`), which raises the total from the
    named-town 133,948 to 134,245 and the credit from $113,102,190 to
    $113,317,957.
    """
    raw = _raw_ptfc_town()
    d = raw.dropna(subset=["town"]).copy()
    d = d.dropna(subset=["n_ptfc"])
    d["key"] = d["town"].astype(str).str.upper().str.strip()
    extra = suppressed_allocation(raw)
    if not extra.empty:
        d = pd.concat([d, extra], ignore_index=True)
    return d


def assign_puma(ptfc: pd.DataFrame, xwalk: pd.DataFrame) -> pd.DataFrame:
    """Allocate every MRS claimant row to PUMAs, proportionally by population.

    Named municipalities join on name. MRS reports unorganised territories as
    one "Unorganized Territory" row per county, which the crosswalk carries as
    "<COUNTY> UT", so those are matched on county instead.

    Where a municipality (or a county's unorganised territory) spans more than
    one PUMA, its claimants and credit are split across them in proportion to
    the population of each piece. With the current crosswalk every weight is
    1.0, so this reproduces a whole assignment exactly.
    """
    named = ptfc[~ptfc["key"].str.contains("UNORGANIZED", na=False)]
    ut_rows = ptfc[ptfc["key"].str.contains("UNORGANIZED", na=False)]

    m = named.merge(xwalk[["key", "PUMACE20", "weight"]], on="key", how="left")

    ut_x = xwalk[xwalk["MuniOrUT"] == "u"].copy()
    ut_x["ut_weight"] = _share_within(ut_x, "county", "pop2020")
    u = ut_rows.merge(ut_x[["county", "PUMACE20", "ut_weight"]], on="county", how="left")
    u = u.rename(columns={"ut_weight": "weight"})

    d = pd.concat([m, u], ignore_index=True)
    if d["PUMACE20"].isna().any():
        missing = sorted(d.loc[d["PUMACE20"].isna(), "town"].unique())
        raise ValueError(f"{len(missing)} rows unassigned: {missing[:10]}")

    d["PUMA"] = d["PUMACE20"].astype(int)
    d["claimants"] = d["n_ptfc"] * d["weight"]
    d["credit_paid"] = d["amt_ptfc"] * d["weight"]

    for col, src in (("claimants", ptfc["n_ptfc"]), ("credit_paid", ptfc["amt_ptfc"])):
        if not np.isclose(d[col].sum(), src.sum(), rtol=1e-9):
            raise ValueError(f"{col} not conserved: {d[col].sum()} vs {src.sum()}")
    return d


# ------------------------------------------------------------- eligibility
def eligible_profile(pums: pd.DataFrame, params=None) -> pd.DataFrame:
    """Characteristics of the ELIGIBLE population, by PUMA, under `params`
    (default: ptfc_engine.BASELINE, the calibration law).

    Deliberately describes the eligible, not all households: take-up is a
    property of the eligible, so its predictors must be measured on them.

    `pct_weak_filing` counts eligible households with neither earned income
    nor an income-tax filing obligation, i.e. no reason to file OTHER THAN
    the credit itself. It measures filing *incentive*, not observed filing
    behaviour -- Maine permits filing solely to claim the PTFC.
    """
    d = pums.copy()
    d["credit"] = E.credit(d, E.BASELINE if params is None else params)
    d["earn"] = d[["WAGP", "SEMP"]].sum(axis=1)
    thr = np.where(d["married"], FILING_THRESHOLD["married"], FILING_THRESHOLD["single"])
    d["no_earn"] = d["earn"] <= 0
    d["weak_filing"] = d["no_earn"] & (d["income"] < thr)

    out = []
    for pm, x in d[d["credit"] > 0].groupby("PUMA"):
        w = x["WGTP"].to_numpy()
        own = x["owner"].to_numpy()
        out.append(dict(
            PUMA=pm,
            eligible=float(w.sum()),
            pct_senior=100 * w[x["senior"].to_numpy()].sum() / w.sum(),
            pct_renter=100 * w[x["renter"].to_numpy()].sum() / w.sum(),
            pct_no_earnings=100 * w[x["no_earn"].to_numpy()].sum() / w.sum(),
            pct_weak_filing=100 * w[x["weak_filing"].to_numpy()].sum() / w.sum(),
            median_income=_wq(x["income"].to_numpy(), w, 0.5),
            median_bill=_wq(x["prop_tax"].to_numpy()[own], w[own], 0.5),
            mean_credit_modelled=float((x["credit"] * w).sum() / w.sum()),
        ))
    return pd.DataFrame(out).set_index("PUMA")


def _wq(x, w, q):
    """Weighted quantile q of x, ignoring NaN."""
    m = ~np.isnan(x)
    x, w = x[m], w[m]
    o = np.argsort(x)
    cw = np.cumsum(w[o]) / w[o].sum()
    return float(x[o][np.searchsorted(cw, q)])


# ----------------------------------------------------------------- take-up
def takeup_by_puma(params=None) -> pd.DataFrame:
    """Take-up = MRS claimants / PUMS-observed eligible, by PUMA.

    Eligibility is scored under `params` (default: ptfc_engine.BASELINE)."""
    pums = load_pums()
    ptfc = load_ptfc_town()
    xwalk = load_xwalk()

    a = assign_puma(ptfc, xwalk)
    num = a.groupby("PUMA").agg(claimants=("claimants", "sum"),
                                credit_paid=("credit_paid", "sum"),
                                towns=("town", "size"))
    t = eligible_profile(pums, params).join(num)
    t["takeup_pct"] = 100 * t["claimants"] / t["eligible"]
    t["mean_credit_actual"] = t["credit_paid"] / t["claimants"]
    t.insert(0, "area", [PUMA_LABEL.get(i, str(i)) for i in t.index])
    cols = ["area", "eligible", "claimants", "takeup_pct", "credit_paid",
            "mean_credit_actual", "mean_credit_modelled", "pct_senior",
            "pct_renter", "pct_no_earnings", "pct_weak_filing",
            "median_income", "median_bill", "towns"]
    return t[cols].reindex(PUMA_ORDER)


def correlates(t: pd.DataFrame) -> pd.DataFrame:
    """Eligible-weighted correlation of take-up with each characteristic.

    Ten observations. Indicative, not inferential.
    """
    w = t["eligible"].to_numpy()

    def wc(a, b):
        am, bm = np.average(a, weights=w), np.average(b, weights=w)
        cov = np.average((a - am) * (b - bm), weights=w)
        return cov / np.sqrt(np.average((a - am) ** 2, weights=w)
                             * np.average((b - bm) ** 2, weights=w))

    y = t["takeup_pct"].to_numpy()
    rows = [(lab, wc(y, t[c].to_numpy())) for lab, c in [
        ("% weak filing incentive", "pct_weak_filing"),
        ("% with no earnings", "pct_no_earnings"),
        ("median income of eligible", "median_income"),
        ("median bill of eligible owners", "median_bill"),
        ("mean credit at stake", "mean_credit_actual"),
        ("% aged 65+", "pct_senior"),
        ("% renter", "pct_renter")]]
    return (pd.DataFrame(rows, columns=["characteristic", "r"])
            .set_index("characteristic")
            .sort_values("r"))


# The six groups are the COARSEST partition in which a union of PUMAs equals a
# union of whole counties, which is the property `crosswalk_check()` rests on.
# Penobscot is split between PUMAs 100 and 300, and Cumberland and York across
# 700-1000, but in both cases the pieces land in the same group, so every one of
# Maine's sixteen counties sits wholly inside exactly one group.
PUMA_GROUPS = {
    "North & east": [100, 300],
    "West & interior": [200],
    "Kennebec": [400],
    "Midcoast/Downeast": [500],
    "Androscoggin": [600],
    "Greater Portland": [700, 800, 900, 1000],
}
COUNTY_GROUPS = {
    "North & east": ["AROOSTOOK", "WASHINGTON", "PENOBSCOT"],
    "West & interior": ["OXFORD", "SOMERSET", "FRANKLIN", "PISCATAQUIS"],
    "Kennebec": ["KENNEBEC"],
    "Midcoast/Downeast": ["HANCOCK", "KNOX", "WALDO", "LINCOLN"],
    "Androscoggin": ["ANDROSCOGGIN"],
    "Greater Portland": ["SAGADAHOC", "CUMBERLAND", "YORK"],
}


def crosswalk_check(t: pd.DataFrame) -> pd.DataFrame:
    """Validate the town-to-PUMA crosswalk without using it.

    The crosswalk is the one load-bearing join in this model: it turns MRS
    town-level claimants into PUMA numerators, so if it misallocates, every
    take-up rate and therefore every scenario cost is wrong.

    MRS reports a county for each town. Because each of the six groups is a whole
    number of counties AND a whole number of PUMAs, the group totals can be built
    two independent ways: by summing counties straight from the MRS file, with no
    crosswalk and no splitting of towns that straddle a PUMA boundary; and by
    summing the PUMAs the crosswalk produced. They must agree exactly.

    This checks the numerator only. Eligibility comes from PUMS by PUMA on both
    routes, so it cannot cross-check itself; `verify()` checks it instead.
    """
    p = load_ptfc_town()
    cty = _county(p["county"])

    seen = set()
    rows = []
    for g, counties in COUNTY_GROUPS.items():
        m = cty.isin([_county(pd.Series([c]))[0] for c in counties])
        seen |= set(counties)
        s = t.loc[PUMA_GROUPS[g]]
        n_cty, n_pm = float(p.loc[m, "n_ptfc"].sum()), float(s["claimants"].sum())
        c_cty, c_pm = float(p.loc[m, "amt_ptfc"].sum()), float(s["credit_paid"].sum())
        rows.append(dict(group=g, claimants_county=n_cty, claimants_puma=n_pm,
                         claimants_diff=n_pm - n_cty,
                         credit_county=c_cty, credit_puma=c_pm,
                         credit_diff=c_pm - c_cty,
                         eligible=float(s["eligible"].sum()),
                         takeup_pct=100 * n_pm / float(s["eligible"].sum())))
    missing = set(cty.unique()) - {_county(pd.Series([c]))[0] for c in seen}
    assert not missing, "counties in the MRS file not covered by COUNTY_GROUPS: %s" % missing
    out = pd.DataFrame(rows)
    out["pass"] = (out["claimants_diff"].abs() < 0.5) & (out["credit_diff"].abs() < 1.0)
    return out


def verify(t: pd.DataFrame) -> pd.DataFrame:
    """Benchmarks the take-up table must clear.

    The first two are conservation checks against the MRS file's own totals,
    including the row it reports without a town (see `suppressed_allocation`).
    The third is also a conservation check: the per-PUMA eligible counts must
    sum to the eligibility counted over the whole frame at once, which catches a
    PUMA dropped or double-counted. The last two are plausibility bands.
    """
    su = 100 * t["claimants"].sum() / t["eligible"].sum()
    mrs = mrs_file_totals()
    d = load_pums()
    statewide = float(d["WGTP"].to_numpy()[E.credit(d, E.BASELINE) > 0].sum())
    checks = [
        (f"claimants sum to the MRS file ({mrs['claimants']:,.0f})",
         f"{t['claimants'].sum():,.0f}", abs(t["claimants"].sum() - mrs["claimants"]) < 50),
        (f"credit paid sums to the MRS file (${mrs['credit']/1e6:.1f}m)",
         f"${t['credit_paid'].sum()/1e6:.1f}m", abs(t["credit_paid"].sum() - mrs["credit"]) < 1e6),
        (f"eligible sums to the ungrouped PUMS count ({statewide:,.0f})",
         f"{t['eligible'].sum():,.0f}", abs(t["eligible"].sum() - statewide) < 50),
        ("all ten PUMAs present", f"{t['claimants'].notna().sum()}", len(t) == 10
         and t["claimants"].notna().all()),
        ("statewide take-up in the 60-75% band", f"{su:.1f}%", 60 <= su <= 75),
        ("modelled mean credit within 10% of actual",
         f"${t['mean_credit_modelled'].mean():.0f} vs ${t['mean_credit_actual'].mean():.0f}",
         abs(t["mean_credit_modelled"].mean() / t["mean_credit_actual"].mean() - 1) < 0.10),
    ]
    return pd.DataFrame(checks, columns=["check", "value", "pass"])


# =================================================== homestead geography (HE)
# The Homestead Exemption scenarios need three quantities that vary by place and
# that the household data cannot supply, because PUMS geography stops at the
# PUMA and carries no municipality, mill rate or exemption status:
#
#   homestead_share  what fraction of owner-occupiers actually hold a homestead.
#                    Ranges 65.6% (PUMA 800) to 84.5% (Aroostook), 73.4%
#                    statewide.
#
#                    The shortfall is not second homes: ACS counts occupied units
#                    at the household's usual residence, so a seasonal home never
#                    enters the owner-occupied denominator. The geography agrees:
#                    Portland is near the bottom at 66.3%, and it is not a
#                    second-home market.
#
#                    The exemption requires having owned a Maine homestead for
#                    the 12 months before April 1, and 26,202 owner-occupiers
#                    moved in within 12 months, up to 22% of the 117,919
#                    residual. That is an upper bound: an in-state owner who
#                    moves keeps eligibility, since the statute says *a*
#                    homestead in Maine, not *this* one. The rest is likely
#                    non-application, ownership form (trusts, LLCs, life
#                    estates) and the MVR 2024 vs ACS 2020-24 timing mismatch.
#                    The scenarios need the count, not the reason.
#   mill_fv          the FULL-VALUE rate. The exemption is certified-ratio
#                    adjusted (36 M.R.S. 683), so exemption x (ratio x mill_rate)
#                    is the dollars saved.
#   mill_delta_pct   per scenario, the proportional change in the rate.
#
# WHY A RATE IS NEEDED AT ALL. The reported bill is used as-is for the baseline
# and for every PTFC scenario. The rate enters only the exemption leg of the HE
# scenarios, where relief is a FLAT dollar amount (d_exempt x mill) identical
# for every homesteader in a town whatever their bill. That flatness is the homestead exemption's progressivity, and no
# proportional adjustment to the observed bill can reproduce it. The mill-change
# leg, by contrast, IS proportional and is applied directly to the reported bill.
#
# WHY NOT THE HOUSEHOLD'S OWN IMPLIED RATE. prop_tax / home_value looks tempting
# and is wrong here: it is an effective rate already net of the existing $25,000
# exemption, and PUMS VALP (an owner's estimate, repriced with a general housing
# deflator) runs high, so it aggregates to 0.00998 against the MVR's 0.01221, a
# 22% level error that would propagate straight into the relief figure.
#
# CAVEAT. Within-PUMA variation is not modelled. Two identical houses in
# neighbouring towns get materially different value from the same exemption
# increase, and a PUMA mean cannot see that.

MVR_PATH = paths.MVR
MVR_YEAR = 2024                       # MVR "year N" = the FY N/N+1 commitment book
SCENARIO_DIR = paths.SCENARIO_DIR
# Labels must match HE_SCENARIOS in ptfc_recalibrate.py exactly: the per-PUMA
# mill lookup is keyed on them. The tables are written by he_resolve_net.
HE_SCENARIO_FILES = {
    "#1 HE $36,600 @ 76%": "s1_raise_exemption.csv",
    "#2 HE $27,600 @ 100%": "s2_homestead_reimb_100.csv",
    "#3 HE $56,400 @ 50%": "s3_homestead_reimb_50.csv",
}
_UT = r"\bUT\b|UNORGANIZED"


def _key(s: pd.Series) -> pd.Series:
    """Normalised municipality name used as a join key."""
    return s.astype(str).str.upper().str.strip()


def _county(s: pd.Series) -> pd.Series:
    """Normalised county name, without a trailing "County"."""
    return (s.astype(str).str.upper()
            .str.replace(r"\s*COUNTY\s*$", "", regex=True).str.strip())


def to_puma(town: pd.DataFrame, xwalk: pd.DataFrame, sum_cols=()) -> pd.DataFrame:
    """Allocate municipality rows to PUMAs. Named munis join on the town key;
    unorganized territories split across their county's UT population. Columns
    in `sum_cols` are scaled by the allocation weight so totals are conserved."""
    t = town.copy()
    named = t[~t["key"].str.contains(_UT, na=False, regex=True)]
    ut = t[t["key"].str.contains(_UT, na=False, regex=True)]
    a = named.merge(xwalk[["key", "PUMACE20", "weight"]], on="key", how="left")
    ux = xwalk[xwalk["MuniOrUT"] == "u"].copy()
    ux["w"] = _share_within(ux, "county", "pop2020")
    b = (ut.merge(ux[["county", "PUMACE20", "w"]], on="county", how="left")
           .rename(columns={"w": "weight"}))
    # A county with no UT row in the crosswalk (Waldo) falls back to that
    # county's dominant PUMA by population, which for every such county is the
    # only PUMA its municipalities belong to.
    if b["PUMACE20"].isna().any():
        dom = (xwalk.groupby(["county", "PUMACE20"])["pop2020"].sum()
                    .reset_index().sort_values("pop2020")
                    .drop_duplicates("county", keep="last")
                    .set_index("county")["PUMACE20"])
        fill = b["county"].map(dom)
        b["weight"] = b["weight"].fillna(1.0).where(b["PUMACE20"].notna(), 1.0)
        b["PUMACE20"] = b["PUMACE20"].fillna(fill)
    d = pd.concat([a, b], ignore_index=True)
    d["weight"] = d["weight"].fillna(1.0)
    for c in sum_cols:
        d[c] = d[c] * d["weight"]
    d = d.dropna(subset=["PUMACE20"])
    d["PUMACE20"] = d["PUMACE20"].astype(int)
    for c in sum_cols:                         # conservation
        lost = 1 - d[c].sum() / town[c].sum()
        if abs(lost) > 1e-6:
            raise ValueError(f"{c} not conserved: {lost:.2%} lost")
    return d


def load_mvr(year: int = MVR_YEAR) -> pd.DataFrame:
    """Municipality rows of the Municipal Valuation Return for one tax year."""
    m = pd.read_csv(MVR_PATH, low_memory=False)
    m = m[(m["Year"] == year) & (m["Aggregation"] == "Muni")].copy()
    m["key"] = _key(m["Place"])
    m["county"] = _county(m["County_ofMuni"])
    m["mill_fv"] = m["mill_rate"] * m["certified_ratio"]
    return m


@lru_cache(maxsize=None)
def _town_levy(year: int) -> pd.Series:
    """Each town's property tax levy (MVR commitment), indexed by town key."""
    m = load_mvr(year)
    levy = pd.Series(pd.to_numeric(m["commitment"], errors="coerce").to_numpy(),
                     index=m["key"].to_numpy())
    return levy[levy.notna() & ~levy.index.duplicated()]


def levy_weighted(change: pd.Series, year: int = MVR_YEAR) -> float:
    """The statewide average of the towns' proportional mill rate changes.

    `change` is indexed by town key (`_key`). Each town is weighted by the
    property tax it levies today, its MVR commitment, so the result is the
    proportional change in the statewide levy that the new rates would raise on
    today's bases. Towns missing from the MVR or without a change are left out.

    This is the one statewide mill measure the model reports: in dashboard.json
    (bundle_geography.mill_summary), the Relief Explorer and the Technical
    Report, and in step 03's solve of Scenarios 1 to 3.
    """
    c = change[np.isfinite(change.to_numpy(float))]
    w = _town_levy(year).reindex(c.index)
    k = w.notna().to_numpy()
    return float((c[k] * w[k]).sum() / w[k].sum())


def homestead_by_puma(year: int = MVR_YEAR) -> pd.DataFrame:
    """Homestead coverage and the full-value rate, by PUMA."""
    m = to_puma(load_mvr(year), load_xwalk(), sum_cols=("hstead_count",))
    pums = load_pums()
    owners = (pd.Series(pums["WGTP"].to_numpy() * pums["owner"].to_numpy(),
                        index=pums["PUMA"]).groupby(level=0).sum())
    g = m.groupby("PUMACE20")
    out = pd.DataFrame({
        "area": pd.Series(PUMA_LABEL),
        "homesteads": g["hstead_count"].sum(),
        "owner_hh": owners,
        # Homestead-weighted, NOT value-weighted. The relief leg is
        # d_exempt x (sum over HOMESTEADS of that town's rate), so each town
        # should count in proportion to how many homesteads it holds. Weighting
        # by taxable value under-weights high-mill towns, which are low-value
        # towns, and understates relief by 13.5% statewide.
        "mill_fv": g.apply(
            lambda t: np.average(t["mill_fv"], weights=t["hstead_count"]),
            include_groups=False),
        "mill_fv_valuewtd": g.apply(
            lambda t: np.average(t["mill_fv"], weights=t["total_taxableval"]),
            include_groups=False),
        "mill_fv_sd": g.apply(
            lambda t: float(np.sqrt(np.average(
                (t["mill_fv"] - np.average(t["mill_fv"], weights=t["hstead_count"]))**2,
                weights=t["hstead_count"]))), include_groups=False),
    })
    out["homestead_share"] = out["homesteads"] / out["owner_hh"]
    return out.loc[PUMA_ORDER]


def he_mill_delta_by_puma() -> pd.DataFrame:
    """Proportional rate change per scenario per PUMA, levy-weighted.

    Levy weighting (taxable value x rate) is the right basis because each
    household's bill is scaled by this figure and tax = value x rate, so it is
    what preserves aggregate tax. A population-weighted figure answers a
    different question: how the rate moves for the typical resident.
    """
    x = load_xwalk()
    cols = {}
    for label, fname in HE_SCENARIO_FILES.items():
        s = pd.read_csv(SCENARIO_DIR / fname)
        s["key"] = _key(s["Place"])
        s["county"] = _county(s["County"])
        s["levy"] = s["mill"] * s["taxable"]
        s["dlevy"] = s["mill_delta"] * s["taxable"]
        d = to_puma(s, x, sum_cols=("levy", "dlevy"))
        g = d.groupby("PUMACE20")
        cols[label] = g["dlevy"].sum() / g["levy"].sum()
    return pd.DataFrame(cols).loc[PUMA_ORDER]
