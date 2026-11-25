#!/usr/bin/env python3
"""Reallocation scenarios 9-13: the household side.

`pipeline/04_reallocation_scenarios.py` solves each town's new mill rate when
the State stops paying revenue sharing or the homestead reimbursement. This
module carries that per-town mill change into PUMA space, raises every owner's
bill by it, and expands the Property Tax Fairness Credit (PTFC) until the
State's delivered cost rises by exactly the freed pool.

THE BUDGET IDENTITY
-------------------
    freed_pool == Model.real_puma(new_params, bills_at_the_new_mill)

`Model.delta` subtracts the baseline credit at baseline bills, so that one line
prices both legs at once:

  AUTOMATIC     Higher bills mean larger credits for every household not already
                at a statutory ceiling, before any parameter moves. The State
                pays this whether or not it intends to.
  DISCRETIONARY What the parameter changes themselves cost.

Scoring a reallocation as "$208.5M freed, $208.5M of new relief" misses the first
leg and overstates the second. `Expansion.solve()` reports them separately.

THE EXEMPTION IS KEPT IN 9-13
-----------------------------
Scenarios 9, 10 and 13 stop revenue sharing; 11 and 12 cut the homestead
reimbursement the State pays towns. In all five the $25,000 exemption still
reaches the household, so the household side is a mill change alone. Scenario 14
(Homestead Plus) abolishes the exemption and is handled in `homestead_plus.py`.

MILL-LINKED REIMBURSEMENTS
--------------------------
The homestead reimbursement and the BETE reimbursement (TRCF Line 22) are each
a rate times the mill times an exempt value, so both rise when a town raises
its mill. The municipal solve puts the reimbursable value in the mill
denominator, and `he_float` / `bete_float` charge the State for the extra
reimbursement its own mill rise earns towns, netting it out of the pool.

WHAT THIS MODEL DOES NOT CAPTURE
--------------------------------
1. Renters see no cost. A renter's counted tax is 15% of rent, and nothing here
   raises rent, although every one of these scenarios raises mill rates that a
   landlord may pass through. Renters therefore appear as pure winners from any
   PTFC expansion. Renter incidence is not quantified.
2. Non-homestead and non-residential property bears the rate rise and receives
   nothing. Vacation homes, commercial and retail parcels are outside PUMS
   altogether, and the ~118,000 owner-occupiers without a homestead are inside it
   but receive no exemption. Both pay more and neither can claim a PTFC unless
   income-eligible.

Both make the reallocations look better than they are.
"""
from dataclasses import replace
from itertools import combinations
from math import factorial

import numpy as np
import pandas as pd

import paths

import ptfc_recalibrate as R          # noqa: E402
import ptfc_takeup as T               # noqa: E402
import fund_totals as F               # noqa: E402

SCEN_DIR = paths.SCENARIO_DIR

# The complete 494-town frame. r9, r10 and r13 cover only 481 because the
# unorganised territories and Moro Plantation receive no revenue sharing, so
# their mill does not move. They must stay in the denominator at zero change,
# or every PUMA holding one of them shows too large a rate rise.
FRAME = "s11_homestead_reimb_50.csv"

SCENARIOS = {
    "9":  ("Abolish revenue sharing I",          "s9_abolish_rev_sharing_1.csv"),
    "10": ("Abolish revenue sharing II",         "s10_abolish_rev_sharing_2.csv"),
    "11": ("Homestead reimbursement 76% -> 50%", "s11_homestead_reimb_50.csv"),
    "12": ("Homestead reimbursement 76% -> 0%",  "s12_homestead_reimb_0.csv"),
    "13": ("All three stacked",                  "s13_all_three.csv"),
}


def gross_pool(scn: str) -> float:
    """What a scenario frees, before the floating reimbursements, to $100,000.

    9 and 10 are the Treasurer's projected Revenue Sharing I and II
    distributions ($208.5m and $56.1m in FY2025; see fund_totals). 11 and 12 are
    what the municipal solve frees across all 494 towns, the `dL` column of the
    scenario's town table (pipeline step 04): for 12 the whole of TRCF Line 21
    ($85.4m in the 2024 MVR); for 11 the part a cut from 76% to 50% frees, net
    of the 50% still paid at the higher mill ($28.5m). 13 stacks 9, 10 and 12
    ($350.0m).
    """
    if scn in ("9", "10"):
        return F.revenue_sharing()["rev_i" if scn == "9" else "rev_ii"]
    if scn in ("11", "12"):
        s = pd.read_csv(SCEN_DIR / SCENARIOS[scn][1])
        return round(float(s["dL"].sum()) / 1e5) * 1e5
    if scn == "13":
        return F.revenue_sharing()["total"] + gross_pool("12")
    raise KeyError(scn)


# The rate at which the State is charged for the homestead reimbursement its own
# mill rise earns towns back. This is not the reimbursement rate surviving the
# reform.
#
# 9 and 10 withdraw revenue sharing while the 76% reimbursement keeps floating
# against the higher mill, so the State pays more and the pool nets down.
#
# 11 is zero even though it keeps a 50% reimbursement: the municipal solve
# returns a loss net of the reimbursement paid at the new mill, so sum(dL) is
# already the State's true saving and the $28.5M is already a net figure.
# Charging again would double-count. 12 and 13 abolish the reimbursement, so
# nothing floats.
#
# No scenario changes BETE: it floats at each municipality's own applicable
# percentage in all five, and that percentage is already inside Line 22, so it
# needs no rate table.
HE_FLOAT_RATE = {"9": 0.76, "10": 0.76, "11": 0.0, "12": 0.0, "13": 0.0}


# The expansion design. One dial t:
#
#     every benefit base   x (1 + t)
#     both maximum credits x (1 + CAP_BASE_RATIO * t)
#     the income offset    4% / (1 + t)
#
# and t solves so the package costs exactly the pool.
#
# Why 3:1: decomposed three ways, between the maximum credit, the bases and the
# offset (`Expansion.split`), this ratio holds the division of the pool
# near-constant across a twelve-fold range of pool size, so the design does not
# change character between $28m and $350m. The shares are computed on every
# run and written to dashboard.json as `scenarios[].expansion_split`.
# A higher ratio buys bottom-decile share on the small pools but drives the
# maximum credit past the single-filer benefit base at Scenarios 9 and 13.
CAP_BASE_RATIO = 3.0

# The three parameter groups the expansion moves, for `Expansion.split`.
SPLIT_GROUPS = ("cap", "base", "offset")


# --------------------------------------------------------------- geography
def _levy_frame() -> pd.DataFrame:
    """Every Maine town with its 2024 levy, keyed for the PUMA crosswalk."""
    f = pd.read_csv(SCEN_DIR / FRAME)
    f["key"] = T._key(f["Place"])
    f["levy"] = f["m0"] * 1000.0 * f["base"]      # m0 is a rate; dmill is in mills
    # `to_puma` splits unorganised territories across their county's UT
    # population and needs a county column to do it. These files carry no
    # County, but a UT's key is its county plus " UT", so derive it.
    f["county"] = (f["key"].str.replace(r"\s*\bUT\b\s*", "", regex=True)
                           .str.replace("UNORGANIZED", "", regex=False).str.strip())
    return f[["key", "county", "base", "levy"]]


def _he_frame() -> pd.DataFrame:
    """Per-town homestead exempt value (MVR line 14f), keyed like the r-files."""
    mvr = T.load_mvr(T.MVR_YEAR)
    f = pd.DataFrame({"key": T._key(mvr["Place"]),
                      "EV": pd.to_numeric(mvr["hstead_eval"], errors="coerce")})
    return f.fillna({"EV": 0.0}).groupby("key", as_index=False)["EV"].sum()


def _town_dmill(scn: str):
    """The scenario's per-town table, keyed, with its mill change `dmill` in mills.

    The mill change comes from the municipal solve, which carries the
    reimbursable homestead and BETE value in its denominator.
    """
    _, fname = SCENARIOS[scn]
    s = pd.read_csv(SCEN_DIR / fname)
    s["key"] = T._key(s["Place"])
    return s


def _bete_frame() -> pd.DataFrame:
    """Per-town reimbursable BETE value (TRCF Line 5b), keyed like the r-files.

    Line 22 / mill. Line 22 is `applicable percentage x mill x exempt value`, so
    the quotient is the reimbursable portion, which is what the municipality
    adds to its tax base (MRS Property Tax Bulletin 28, section 6.D) and what
    the State pays at the new mill. Matches the MVR's own Line 5b in all 494
    towns to within $0.02.
    """
    mvr = T.load_mvr(T.MVR_YEAR)
    m = pd.to_numeric(mvr["mill_rate"], errors="coerce")
    r22 = pd.to_numeric(mvr["TRCF: Line 22"], errors="coerce")
    f = pd.DataFrame({"key": T._key(mvr["Place"]), "BT": r22 / m})
    return f.fillna({"BT": 0.0}).groupby("key", as_index=False)["BT"].sum()


def bete_float(scn: str) -> float:
    """Extra BETE reimbursement the State pays because the mill rose.

    Priced at the damped mill, like `he_float`, because that is the mill the
    town actually sets. Every reallocation leaves BETE in place, so this is
    nonzero in all five.
    """
    s = _town_dmill(scn)
    s = s.merge(_bete_frame(), on="key", how="left")
    s["BT"] = s["BT"].fillna(0.0)
    return float(((s["dmill"] / 1000.0) * s["BT"]).sum())


def he_float(scn: str) -> float:
    """Extra homestead reimbursement the State pays because the mill rose.

    Priced at the damped mill, because that is the mill the town actually sets
    once it anticipates the reimbursement. Zero where `HE_FLOAT_RATE` is zero.
    """
    r = HE_FLOAT_RATE[scn]
    if r == 0.0:
        return 0.0
    s = _town_dmill(scn)
    s = s.merge(_he_frame(), on="key", how="left")
    s["EV"] = s["EV"].fillna(0.0)
    return float((r * (s["dmill"] / 1000.0) * s["EV"]).sum())


def mill_delta_by_puma(scn: str) -> pd.Series:
    """Proportional mill change per PUMA, levy-weighted, for one scenario.

    Levy weighting is the right basis because a household's bill scales with
    this figure and tax = value x rate, so it is what preserves aggregate tax.
    Matches `ptfc_takeup.he_mill_delta_by_puma`, which does the same job for the
    homestead scenarios 1-3.
    """
    s = _town_dmill(scn)
    s["dlevy"] = s["dmill"] * s["base"]

    full = _levy_frame().merge(s[["key", "dlevy"]], on="key", how="left")
    full["dlevy"] = full["dlevy"].fillna(0.0)     # untouched towns: no change

    x = T.load_xwalk()
    d = T.to_puma(full, x, sum_cols=("levy", "dlevy"))
    g = d.groupby("PUMACE20")
    out = (g["dlevy"].sum() / g["levy"].sum()).loc[T.PUMA_ORDER]
    out.name = scn
    return out


# ------------------------------------------------------------------ engine
class Expansion:
    """PTFC expansion against a raised mill rate, solved to a budget."""

    def __init__(self, model: "R.Model", scn: str):
        self.m = model
        self.scn = scn
        self.name, _ = SCENARIOS[scn]
        self.gross_pool = gross_pool(scn)
        # The mill-linked reimbursements the State pays at the higher mill come
        # out of the pool it frees.
        self.he_float = he_float(scn)
        self.bete_float = bete_float(scn)
        self.pool = self.gross_pool - self.he_float - self.bete_float
        self.dmill = mill_delta_by_puma(scn)
        puma = model.df["PUMA"].to_numpy()
        self.mp = np.array([self.dmill[q] for q in puma])
        # The exemption is unchanged, so only the rate moves: owners' bills at
        # the new mill. Renters' counted tax is unchanged.
        self.bills = np.where(model.owner, model.tax0 * (1 + self.mp), model.tax0)
        self.p0 = model.p0

    # -- costing -----------------------------------------------------------
    def cost(self, p=None) -> float:
        """Delivered cost above current law, at the raised bills."""
        return self.m.real_puma(self.p0 if p is None else p, self.bills)

    @property
    def automatic(self) -> float:
        """What the higher bills cost the State before any parameter moves."""
        return self.cost(self.p0)

    # -- parameter families ------------------------------------------------
    def with_bases(self, p, k: float):
        return replace(p, base_single=self.p0.base_single * k,
                       base_hoh_one=self.p0.base_hoh_one * k,
                       base_joint_multi=self.p0.base_joint_multi * k,
                       base_senior=self.p0.base_senior * k)

    def with_offset(self, p, rate: float):
        return replace(p, rate_income=rate)

    # -- solving -----------------------------------------------------------
    @staticmethod
    def _bisect(f, lo, hi, target, iters=80):
        """Smallest x in [lo, hi] with f(x) >= target, assuming f is monotone up."""
        for _ in range(iters):
            mid = (lo + hi) / 2
            if f(mid) < target:
                lo = mid
            else:
                hi = mid
        return hi

    def g_params(self, t: float):
        """The expansion's parameters at dial setting `t`."""
        p = self.with_bases(self.p0, 1.0 + t)
        p = replace(p, cap_under65=self.p0.cap_under65 * (1.0 + CAP_BASE_RATIO * t),
                    cap_senior=self.p0.cap_senior * (1.0 + CAP_BASE_RATIO * t))
        return self.with_offset(p, self.p0.rate_income / (1.0 + t))

    def solve(self):
        """Solve the one-dial expansion so it costs exactly the pool."""
        r = CAP_BASE_RATIO
        budget, auto = self.pool, self.automatic
        stages = [dict(stage="automatic", lever="none (bills rise)",
                       setting="current law", cumulative=auto, stage_cost=auto,
                       headroom=budget - auto, note="")]
        if auto >= budget:
            stages[0]["note"] = ("the higher bills alone cost more than the pool "
                                 "frees; there is nothing left to expand with")
            return self._result(stages, self.p0, budget, auto, exhausted_at="automatic")
        f = lambda t: self.cost(self.g_params(t))
        t = self._bisect(f, 0.0, 200.0, budget)
        p = self.g_params(t)
        stages.append(dict(
            stage="joint", lever="one dial t at %g:1" % r,
            setting="t=%.4f" % t, value=float(t),
            cumulative=self.cost(p), stage_cost=self.cost(p) - auto,
            headroom=budget - self.cost(p),
            note="bases x%.4f, caps x%.4f, offset %.3f%%"
                 % (1 + t, 1 + r * t, p.rate_income * 100)))
        return self._result(stages, p, budget, auto, exhausted_at=None)

    def _result(self, stages, p, budget, auto, exhausted_at):
        spent = self.cost(p)
        return dict(scenario=self.scn, name=self.name, pool=budget,
                    automatic=auto, discretionary=spent - auto,
                    delivered=spent, shortfall=budget - spent,
                    exhausted_at=exhausted_at, params=p,
                    stages=pd.DataFrame(stages))

    # -- decomposition -----------------------------------------------------
    def _with_groups(self, p, groups):
        """Current law, with the named parameter groups moved to their values in p."""
        q = self.p0
        if "cap" in groups:
            q = replace(q, cap_under65=p.cap_under65, cap_senior=p.cap_senior)
        if "base" in groups:
            q = replace(q, base_single=p.base_single, base_hoh_one=p.base_hoh_one,
                        base_joint_multi=p.base_joint_multi,
                        base_senior=p.base_senior)
        if "offset" in groups:
            q = replace(q, rate_income=p.rate_income)
        return q

    def split(self, p) -> dict:
        """How the discretionary spend divides between the three parameter groups.

        The maximum credits, the benefit bases and the income offset interact,
        so the cost of moving one depends on whether the others have moved. A
        Shapley decomposition averages each group's marginal cost over every
        order in which the three could be moved. The three shares sum to one.
        The automatic leg is excluded: it is paid before any parameter moves.
        """
        n = len(SPLIT_GROUPS)
        auto = self.automatic
        v = {frozenset(s): self.cost(self._with_groups(p, s)) - auto
             for k in range(n + 1) for s in combinations(SPLIT_GROUPS, k)}
        whole = v[frozenset(SPLIT_GROUPS)]
        out = {}
        for g in SPLIT_GROUPS:
            rest = [x for x in SPLIT_GROUPS if x != g]
            phi = 0.0
            for k in range(n):
                wt = factorial(k) * factorial(n - k - 1) / factorial(n)
                for s in combinations(rest, k):
                    phi += wt * (v[frozenset(s) | {g}] - v[frozenset(s)])
            out[g] = phi / whole
        return out

    # -- incidence ---------------------------------------------------------
    def net(self, p):
        """Per-household net gain: expected extra credit less the extra bill.

        The credit leg is take-up weighted because a household only receives
        what it claims. The bill leg is not, because the higher rate is paid
        whether or not anyone files a return. That asymmetry is why these
        scenarios can leave a household worse off.
        """
        dcredit = self.m.delta(p, self.bills) * self.m.tau_h
        dbill = self.bills - self.m.tax0
        return dcredit - dbill
