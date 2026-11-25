#!/usr/bin/env python3
"""Scenarios 15-19, the Task Force scenarios: revenue-neutral packages.

Each package cuts Revenue Sharing I, sets the homestead reimbursement rate and
the homestead exemption, and pays a Fairness Credit with fixed parameters. The
Revenue Sharing I cut is solved so the State's net cost is zero (see
`bundle_scenarios.py`). `Combo` prices one package and writes its town table.

TOWNS. One identity per town, the homestead engine's (he_resolve_net.he_model)
with the revenue-sharing loss added to what the town must raise:

    mill1 = (NetToBeRaised + dRS) / (taxable(E) + r x exempt(E) + BETE value)

dRS is the anticipated revenue sharing (TRCF Line 12) the town loses. Each town
keeps its own ratio of Line 12 to the Treasurer's projection, clipped to
0.5-1.5, with blank lines imputed at the median.

STATE, a year:  - revenue sharing not paid
                + change in homestead reimbursement (r times the new exempt
                  value, at the new mill) against today's 76%
                + change in BETE reimbursement (it floats with the mill)
                + Fairness Credit at the new bills and parameters, above
                  today's, at today's claiming rates

HOUSEHOLDS. As the homestead scenarios (Model.he_bill / _he_legs): a homestead
leg (mill change plus a flat exemption) and a non-homestead leg (mill change
only), weighted by the area's homestead share; renters see no mill change (no
rent pass-through, as everywhere in the model). The credit leg is take-up
weighted, the bill leg is not.
"""
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

import paths
import he_resolve_net as H   # noqa: E402
import ptfc_engine as E      # noqa: E402
import ptfc_takeup as T      # noqa: E402
import fund_totals as F      # noqa: E402

REVI_POOL = F.revenue_sharing()["rev_i"]   # Revenue Sharing I ($208.5m in FY2025), as Scenario 9
CURRENT_RATE = 0.76                # today's homestead reimbursement rate
LO, HI = 0.5, 1.5                  # bounds on each town's Line 12 / projection ratio


def revshare_loss(frac):
    """Per-town Line 12 loss when every town's Rev I falls by `frac`."""
    s = pd.read_csv(paths.SCENARIO_DIR / "s9_abolish_rev_sharing_1.csv")
    l12, proj = s["l12"], s["proj"]
    proj_new = (proj - frac * s["revI"]).clip(lower=0)
    blank = (l12 == 0) & (proj > 0)
    r_obs = (l12 / proj.where(proj > 0)).clip(LO, HI)
    r_med = float(r_obs[(~blank) & (proj > 0)].median())
    r = r_obs.where(~blank, r_med).fillna(r_med)
    l12_eff = l12.where(~blank, r * proj)
    dl = (l12_eff - r * proj_new).clip(lower=0)
    return pd.DataFrame({"key": T._key(s["Place"]), "dRS": dl.to_numpy()})


def towns(exemption, rate, revi_cut):
    """Per-town mills under the package, and the State's change in cost by leg."""
    mvr = H.load_mvr()
    mvr["key"] = T._key(mvr["Place"])
    # Net of the no-cut run: the ratio clip leaves a $0.12m "loss" at a zero cut
    # in towns whose Line 12 exceeds 1.5x the projection; only the cut should count.
    z = revshare_loss(0.0)
    rs = revshare_loss(revi_cut / REVI_POOL).merge(z, on="key", suffixes=("", "_0"))
    rs["dRS"] = (rs["dRS"] - rs["dRS_0"]).clip(lower=0)
    mvr = mvr.merge(rs[["key", "dRS"]], on="key", how="left")
    mvr["dRS"] = mvr["dRS"].fillna(0.0)
    exempt = (mvr["hstead_max_count"] * exemption * mvr["certified_ratio"] * H.cap_ratio(exemption)
              + mvr["hstead_part_val"].fillna(0))
    reimbval = rate * exempt
    taxable = mvr["cur_TaxableValue"] + mvr["hstead_eval"] - exempt
    mill = (mvr["cur_NetToBeRaised"] + mvr["dRS"]) / (taxable + reimbval + mvr["cur_BETE_Value"])
    t = pd.DataFrame({
        "Place": mvr["Place"].values, "County": mvr["County_ofMuni"].values,
        "taxable": taxable.values, "mill": mill.values,
        "he_reimb": (reimbval * mill).values, "bete_reimb": (mvr["cur_BETE_Value"] * mill).values,
        "commitment": (mill * taxable).values, "mill_delta": (mill - mvr["cur_MillRate"]).values,
        "dRS": mvr["dRS"].values,
    })
    state = dict(
        revshare=-revi_cut,
        reimb=float(t["he_reimb"].sum() - mvr["cur_HE_Reimb"].sum()),
        bete=float(t["bete_reimb"].sum() - mvr["cur_BETE_Reimb"].sum()),
    )
    # Not a leg of the net cost: what lowering the reimbursement rate saves on
    # today's exempt value at the package's mill rates, for `Combo.redirected`.
    state["rate_saving"] = float((max(CURRENT_RATE - rate, 0.0)
                                  * mvr["hstead_eval"].fillna(0.0) * mill).sum())
    return t, state


def puma_dmill(t):
    """Proportional mill change per PUMA, levy-weighted."""
    s = t.copy()
    s["key"] = T._key(s["Place"])
    s["county"] = T._county(s["County"])
    s["levy"] = s["mill"] * s["taxable"]
    s["dlevy"] = s["mill_delta"] * s["taxable"]
    g = T.to_puma(s, T.load_xwalk(), sum_cols=("levy", "dlevy")).groupby("PUMACE20")
    return g["dlevy"].sum() / g["levy"].sum()


@dataclass
class TwoTierParams(E.Params):
    """The two-tier PTFC formula of Scenario 19: 100% of counted tax above 4% of
    income up to $2,000, plus 50% of the rest, at most $5,000 in total; counted
    tax capped at a single $8,000 benefit base; no age or household-size
    distinction. Renters count 15% of rent, as today."""
    two_tier: bool = True
    tier1: float = 2_000.0
    tier2_rate: float = 0.50
    max_total: float = 5_000.0
    base_all: float = 8_000.0


def credit(df, p, bill, p0):
    """The credit under `p` at bills `bill`: the two-tier formula when `p` is a
    `TwoTierParams`, otherwise the PTFC. `p0` is not used by either formula; it
    is kept so callers can pass current-law parameters uniformly."""
    if getattr(p, "two_tier", False):
        import congregate_care as CC
        tax = np.asarray(bill, float)
        counted = np.minimum(tax + p.rate_rent * CC.rent_for_credit(df), p.base_all)
        excess = np.maximum(counted - p.rate_income * np.maximum(df["income"].to_numpy(), 0.0), 0.0)
        c = np.minimum(excess, p.tier1) + p.tier2_rate * np.maximum(excess - p.tier1, 0.0)
        return np.minimum(np.minimum(c, p.max_total), tax + p.rate_rent * CC.rent_for_credit(df))
    return E.credit(df, p, bill)


def params(p0, t, ratio):
    """Benefit bases x (1 + t) and maximum credits x (1 + ratio x t)."""
    return replace(p0, base_single=p0.base_single * (1 + t), base_hoh_one=p0.base_hoh_one * (1 + t),
                   base_joint_multi=p0.base_joint_multi * (1 + t), base_senior=p0.base_senior * (1 + t),
                   cap_under65=p0.cap_under65 * (1 + ratio * t),
                   cap_senior=p0.cap_senior * (1 + ratio * t))


class Combo:
    """One package: an exemption, a reimbursement rate and a Revenue Sharing I cut."""

    def __init__(self, m, exemption, rate, revi_cut, town_file=None):
        self.m = m
        self.revi_cut = float(revi_cut)
        self.rate = float(rate)
        self.exemption = float(exemption)
        self.town_file = town_file
        self.towns, self.state = towns(self.exemption, self.rate, self.revi_cut)
        dm = puma_dmill(self.towns)
        mp = np.array([dm[q] for q in m.df["PUMA"].to_numpy()])
        d_eff = np.minimum(self.exemption - 25_000.0, m.room_h)
        self.bill_hs = np.where(m.owner, np.maximum(m.tax0 * (1 + mp) - d_eff * m.mill_h, 0.0), m.tax0 * (1 + mp))
        self.bill_no = m.tax0 * (1 + mp)
        self.w = np.where(m.owner, m.hshare_h, 0.0)
        self.tau = m.tau_h

    def ptfc_cost(self, p):
        """Delivered credit cost above current law, take-up weighted."""
        m = self.m
        c_hs = credit(m.df, p, self.bill_hs, m.p0) - m.base
        c_no = credit(m.df, p, self.bill_no, m.p0) - m.base
        return float(((self.w * c_hs + (1 - self.w) * c_no) * self.tau * m.W).sum())

    def fix(self, p):
        """Adopt credit parameters `p` and return the State's net change in cost."""
        self.p = p
        return self.state["revshare"] + self.state["reimb"] + self.state["bete"] + self.ptfc_cost(p)

    def redirected(self):
        """The money the package takes from towns' State aid: the Revenue Sharing I
        cut, plus what cutting the reimbursement rate below 76% saves on today's
        exempt value, valued at the package's mill rates (higher than today's, so
        more than the $28.5m the same cut saves at today's rates)."""
        return self.revi_cut + self.state["rate_saving"]

    def legs(self):
        """(homesteader net gain, non-homesteader net gain) per household."""
        m, p = self.m, self.p
        g_hs = -(self.bill_hs - m.tax0) + (credit(m.df, p, self.bill_hs, m.p0) - m.base) * self.tau
        g_no = -(self.bill_no - m.tax0) + (credit(m.df, p, self.bill_no, m.p0) - m.base) * self.tau
        return g_hs, g_no

    def vec(self):
        """Per-household net gain, the two legs blended by homestead share."""
        g_hs, g_no = self.legs()
        return self.w * g_hs + (1 - self.w) * g_no

    def write_towns(self):
        self.towns.drop(columns=["dRS"]).to_csv(paths.SCENARIO_DIR / self.town_file, index=False)
