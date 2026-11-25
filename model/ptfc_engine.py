"""
Maine Property Tax Fairness Credit (PTFC): a closed-form engine over ACS PUMS.

Implements 36 M.R.S. sec.5219-KK and applies it to the 2020-2024 5-year Maine
ACS PUMS with household weights, using each respondent's observed property tax
(TAXAMT), household income (HINCP) and tenure (TEN). PolicyEngine's synthetic
microdata is not used because it does not reproduce Maine's tenure and property
tax distribution: it has no owners who own free and clear (42% do in PUMS), 70%
of its Maine owners carry no property tax bill (2% in PUMS), and the state rests
on 520 records. `validate_against_policyengine.py` checks this implementation
household by household against PolicyEngine's household calculator.

The formula:

    base     = senior_base            if max(age head, age spouse) >= 65
               else base[filing status, dependent count]
    crpt     = property_tax + rate_rent * annual_rent
    uncapped = max( min(base, crpt) - rate_income * income , 0 )
    credit   = min( min(uncapped, cap[age]) , crpt )

The benefit base caps the counted tax BEFORE the income offset applies, so a
household whose bill is below the base gains nothing when the base rises. That
asymmetry drives most of the distributional results.
"""
from dataclasses import dataclass, replace
import numpy as np
import pandas as pd

import congregate_care as CC  # noqa: E402


# ---------------------------------------------------------------- parameters
@dataclass
class Params:
    """PTFC parameters. Defaults are TY2025 law."""
    base_single: float = 2_550.0
    base_hoh_one: float = 3_300.0        # HoH w/ 1 dep, or MFJ w/ 0 deps
    base_joint_multi: float = 4_050.0    # HoH w/ 2+ deps, or MFJ w/ 1+ deps
    base_senior: float = 4_100.0         # age 65+, overrides filing status
    cap_under65: float = 1_000.0
    cap_senior: float = 2_000.0
    rate_income: float = 0.04
    rate_rent: float = 0.15


# MRS's claimant counts and payments are for TY2024. The model calibrates
# take-up by dividing those claimants by the households eligible under TY2025
# law (see ptfc_takeup, VINTAGE), and uses TY2026 law as the baseline for every
# scenario. TY2024 law is used only to reproduce the validation against what
# MRS paid for TY2024 (pipeline/07_validate.py).
#
# TY2025 and TY2026 differ in five fields. Four are the benefit bases, which
# 36 M.R.S. sec.5403(6) indexes annually: the statutory bases in
# sec.5219-KK(1)(A-1) ($2,050 / $2,650 / $3,250 for subparagraphs (1) to (3),
# $4,000 for (4)) are adjusted by the Chained CPI (BLS series SUUR0000SA0) for
# the 12 months ending 30 June of the preceding year, relative to the 12 months
# ending 30 June 2017 for the first three and 30 June 2023 for the senior base,
# with any increase rounded DOWN to the next lowest $50. That reproduces all
# twelve published amounts for TY2024-TY2026, at factors of 1.213964 /
# 1.249638 / 1.279160 and 1.000000 / 1.029386 / 1.053705. The rounding binds:
# $2,622.30 becomes $2,600 and $3,389.80 becomes $3,350.
#
# The maximum credits are not indexed and change only by amendment. LD 2212
# raised the under-65 cap from $1,000 to $1,500 for TY2026 and left the senior
# cap at $2,000, so that is the only policy change between the two years.
#
# Because the bases decide who qualifies, eligibility also differs: 198,876
# eligible households under TY2026, 196,956 under TY2025 and 193,935 under
# TY2024.
TY2025 = Params()
TY2026 = replace(TY2025,
                 base_single=2_600.0,
                 base_hoh_one=3_350.0,
                 base_joint_multi=4_150.0,
                 base_senior=4_200.0,
                 cap_under65=1_500.0)

# TY2024 law, the year of MRS's claimant file. Used only by the validation
# (pipeline/07_validate.py). Bases from the 2024 Schedule PTFC/STFC; the
# under-65 maximum was $1,000 until LD 2212.
TY2024 = replace(TY2025,
                 base_single=2_450.0,
                 base_hoh_one=3_200.0,
                 base_joint_multi=3_900.0,
                 base_senior=4_000.0,
                 cap_under65=1_000.0)

# TY2025 law, the take-up calibration year.
BASELINE = TY2025


# ---------------------------------------------------------------- the credit
def benefit_base(df: pd.DataFrame, p: Params) -> np.ndarray:
    """Per-household benefit base by filing status, dependents and age."""
    married = df["married"].to_numpy()
    ndep = df["n_dep"].to_numpy()
    base = np.where(
        married,
        np.where(ndep == 0, p.base_hoh_one, p.base_joint_multi),
        np.where(ndep == 0, p.base_single,
                 np.where(ndep == 1, p.base_hoh_one, p.base_joint_multi)),
    )
    return np.where(df["senior"].to_numpy(), p.base_senior, base)


def credit(df: pd.DataFrame, p: Params, prop_tax=None) -> np.ndarray:
    """Per-household PTFC in dollars. `prop_tax` overrides the column (used by
    the Homestead Exemption scenarios, which change the bill)."""
    tax = df["prop_tax"].to_numpy() if prop_tax is None else np.asarray(prop_tax)
    rent = CC.rent_for_credit(df)   # occupancy portion, not the reported fee
    income = np.maximum(df["income"].to_numpy(), 0.0)

    crpt = tax + p.rate_rent * rent
    base = benefit_base(df, p)
    cap = np.where(df["senior"].to_numpy(), p.cap_senior, p.cap_under65)

    uncapped = np.maximum(np.minimum(base, crpt) - p.rate_income * income, 0.0)
    c = np.minimum(np.minimum(uncapped, cap), crpt)
    return c


# ------------------------------------------------- Homestead Plus (scenario 14)
@dataclass(frozen=True)
class HomesteadPlusParams:
    """Homestead Plus credit schedule, as set out in the Homestead Plus
    discussion draft.

    A MARGINAL bracket schedule: within each band of property tax measured as a
    share of income, the State pays the band's rate of the tax that falls in
    that band. The draft's text can be read as a sum of cumulative excesses, but
    its worked illustration gives bands of income with a taxpayer share of
    100% / 60% / 40% / 20%, and only the marginal reading reproduces its own
    worked example (an Auburn couple receiving $3,526).

    The defaults are the draft's schedule. They reproduce the Auburn example to
    the dollar, the 14 cells of its two percent-reduction tables, and both
    anchors of its maximum-benefit chart ($4,800 single and $6,400 multiple at
    zero income, reaching zero at $150,000 and $200,000 of income).
    """
    thresholds: tuple = (0.04, 0.08, 0.12)   # band edges, as a share of income
    rates: tuple = (0.0, 0.40, 0.60, 0.80)   # state share within each band
    cap_single: float = 6_000.0              # eligible COUNTED TAX, not credit
    cap_multi: float = 8_000.0
    rate_rent: float = 0.15                  # as 36 M.R.S. 5219-KK

    def __post_init__(self):
        assert len(self.rates) == len(self.thresholds) + 1


# The schedule as drafted.
HP_V1 = HomesteadPlusParams()

# The Scenario 14 schedule: brackets at 2 / 3 / 5 / 8% of income, State shares
# 0 / 50 / 80 / 85 / 90%.
#
# The drafted schedule pays nothing below a 4% burden, and the median Maine
# owner pays 3.19% of income (3.74% once the homestead exemption is repealed),
# so it spends only a third of the pool its own reform frees. Capacity is the
# binding constraint: one point of State share is worth about $6.9m in the 0-2%
# band and $4.7m in 2-6%, but under $0.9m in each band above 6%, so a schedule
# that spends the pool must reach well below a 4% burden.
#
# The top share is 90%, not 100%: a 100% band would create a hard burden
# ceiling but leave households above the top threshold with no stake in their
# own assessment. The first band is zero because the bands are shares of income,
# so a rate there pays in proportion to income and is the least progressive
# dollar in the schedule.
#
# Consequences: there is no burden ceiling, since the State's share approaches
# but never reaches 90%; and in the bottom income decile only 53% of households
# are better off. That decile is 47% owners, every owner loses the homestead
# exemption, and 34% of the decile does not claim the credit, so
# the reform trades an automatic benefit for a claimed one.
HP_CANONICAL = HomesteadPlusParams(thresholds=(0.02, 0.03, 0.05, 0.08),
                                   rates=(0.0, 0.50, 0.80, 0.85, 0.90))


def homestead_plus(df: pd.DataFrame, p: HomesteadPlusParams = HP_V1,
                   prop_tax=None) -> np.ndarray:
    """Per-household Homestead Plus payment in dollars.

    Differs from `credit()` in three ways that matter distributionally. There is
    no benefit base, so a large bill is not truncated before the offset applies.
    There is no cap on the credit itself, only on the counted tax that
    qualifies. And there is no senior distinction: households are split by size
    alone, so the preferential senior base and cap in current law disappear.

    Household size is the PUMS person count `NP`, which is what "single person
    household" and "multiple person household" mean. Married-or-has-dependents
    is not a substitute: it would classify an unmarried adult sharing a home as
    a single-person household.
    """
    tax = df["prop_tax"].to_numpy() if prop_tax is None else np.asarray(prop_tax)
    rent = CC.rent_for_credit(df)   # occupancy portion, not the reported fee
    income = np.maximum(df["income"].to_numpy(), 0.0)

    crpt = tax + p.rate_rent * rent
    multi = df["NP"].to_numpy() > 1
    eligible = np.minimum(crpt, np.where(multi, p.cap_multi, p.cap_single))

    edges = ([np.zeros_like(income)]
             + [t * income for t in p.thresholds]
             + [np.full_like(income, np.inf)])
    c = np.zeros_like(eligible, dtype=float)
    for i, r in enumerate(p.rates):
        if r == 0.0:
            continue
        c += r * np.clip(np.minimum(eligible, edges[i + 1]) - edges[i], 0.0, None)
    return c
