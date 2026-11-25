"""The eight equal-cost scenarios (1-8): one definition each, in one place.

Each scenario stores what it means -- its target and its free parameter -- not
the parameter's value. Values are re-solved from the current model on every
call, so a change to the data propagates instead of leaving a stale constant.
The one exception is the Homestead scenarios' cost, which needs the municipal
model and is carried in `ptfc_recalibrate.HE_SCENARIOS`.

Every scenario is solved to $35M of NET cost to the State. For a refundable
credit, net cost and delivered relief are the same number. For the Homestead
scenarios they are not: the exemption displaces PTFC the State no longer pays,
and relief also reaches households through the mill-rate change, which is
financed by non-homestead property. So state_cost and delivered diverge on
rows 1-3 and are identical on 4-8.

The scenarios land on a grid rather than exactly on $35M: the Homestead
exemptions are solved to the nearest $100 and Scenario 7's phase-out on a
$5,000 income band, so each row is within about $0.3M of the target.
"""
from dataclasses import dataclass, replace
from typing import Callable
import pandas as pd

import ptfc_recalibrate as R
import ptfc_engine as E
import ceiling_redesign as C


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    family: str                # "HE" | "PTFC" | "CEILING"
    lever: str                 # what the Task Force is being asked to move
    build: Callable            # model (or Redesign) -> payload


# ------------------------------------------------------------------ 1-3, HE
def _he(sid):
    """Build a Homestead scenario from its id. The label is looked up at call
    time, because it carries the solved exemption and changes whenever the
    exemptions are re-solved."""
    def f(m):
        label = next(l for s_, l, _E, _r in R.he_canonical() if s_ == sid)
        dex, mp, gross, bete = R.HE_SCENARIOS[label]
        return dict(label=label, dex=dex, mp=mp, gross=gross, bete=bete)
    return f


# ----------------------------------------------------------------- 4-6, PTFC
def _s4(m):
    k = m.solve_multiplier()
    return dict(params=R.scale_bases(k, m.p0), desc="benefit bases x%.4f" % k)


def _s5(m):
    r = m.solve_offset(3_000.0, 4_000.0)
    return dict(params=replace(m.p0, rate_income=r, cap_under65=3_000.0,
                               cap_senior=4_000.0),
                desc="caps $3,000/$4,000, income offset %.4f%%" % (100 * r))


def _s6(m):
    """Caps fixed at x1.5, bases solved. Fixing the caps puts 52.2% of the money
    in the bottom three deciles, against 34.8% if bases and caps were scaled by
    the same multiplier, because raising the cap pays households already at the
    maximum while raising the bases extends eligibility upward. Multipliers
    apply to the baseline's own bases and caps."""
    kb = R.solve_hybrid_base(m, 1.5)
    s, h, j, sen = (m.p0.base_single, m.p0.base_hoh_one,
                    m.p0.base_joint_multi, m.p0.base_senior)
    return dict(params=replace(m.p0, base_single=s * kb, base_hoh_one=h * kb,
                               base_joint_multi=j * kb, base_senior=sen * kb,
                               cap_under65=2_250.0, cap_senior=3_000.0),
                desc="caps x1.5, bases x%.4f" % kb)


# -------------------------------------------------------------- 7-8, CEILING
def _rec(i):
    """Liability-ceiling designs from `ceiling_redesign.recommended()`. Neither
    has a cliff: Scenario 7 phases its guarantee out over an income band, and
    Scenario 8 counts only the tax on the first part of home value."""
    def f(rd):
        return C.recommended(rd)[i]
    return f


CANONICAL = [
    Scenario("1", "Raise the Homestead Exemption", "HE",
             "exemption amount, reimbursement held at 76%", _he("#1")),
    Scenario("2", "Homestead reimbursement to 100%", "HE",
             "reimbursement rate, exemption solved", _he("#2")),
    Scenario("3", "Homestead reimbursement to 50%", "HE",
             "reimbursement rate, exemption solved", _he("#3")),
    Scenario("4", "Raise the benefit bases", "PTFC",
             "benefit bases, caps unchanged", _s4),
    Scenario("5", "Raise the maximum credit", "PTFC",
             "caps, with the income offset solved", _s5),
    Scenario("6", "Hybrid: bases and caps", "PTFC",
             "caps and bases together", _s6),
    Scenario("7", "Senior liability ceiling", "CEILING",
             "6% of income, 65+, phased out by income", _rec(0)),
    Scenario("8", "General liability ceiling", "CEILING",
             "6% of income, all ages, tax apportioned by home value", _rec(1)),
]


def vectors(model: "R.Model | None" = None, redesign=None) -> dict:
    """id -> per-household delivered relief, as an expectation, in dollars.

    This is the right object for anything that SUMS: decile shares, group means,
    geography. It is the WRONG object for COUNTING households on rows 1-3.
    `he_delivered()` blends the homesteader and non-homesteader outcomes by the
    PUMA homestead share, so `v > 0` holds for most owners even where the
    non-homesteader leg is a loss; counting that way would report more gaining
    households than the ~324,000 homesteads that exist. `build()` counts with
    `Model._he_legs()` instead, weighting each leg separately.
    """
    m = R.Model() if model is None else model
    rd = None
    out = {}
    for sc in CANONICAL:
        if sc.family == "HE":
            p = sc.build(m)
            out[sc.id] = m.he_delivered(p["dex"], p["mp"], p["label"])
        elif sc.family == "PTFC":
            out[sc.id] = m.delta(sc.build(m)["params"]) * m.tau_h
        else:
            if rd is None:
                rd = C.Redesign(m) if redesign is None else redesign
            out[sc.id] = rd.gain(sc.build(rd))
    return out


def build(model: "R.Model | None" = None, redesign=None) -> pd.DataFrame:
    """Evaluate all eight on one model. Returns one row per scenario."""
    m = R.Model() if model is None else model
    W = m.W.astype(float)
    rd = None
    rows = []
    for sc in CANONICAL:
        if sc.family == "HE":
            p = sc.build(m)
            d = m.he_delivered(p["dex"], p["mp"], p["label"])
            new = m.he_bill(p["dex"], p["mp"], p["label"])
            _, _, share = m._geo(p["label"])
            clawback = float((m.delta(m.p0, new) * m.tau_h * share * W).sum())
            # Three legs, not two. The homestead reimbursement the State pays,
            # the BETE reimbursement it also pays because the same mill change
            # moves that too, and the PTFC it no longer pays because bills fell.
            state = p["gross"] + p["bete"] + clawback
            delivered = float((d * W).sum())
            # EXPECTED count, not a count of positive expectations: d > 0 holds
            # for most owners even when the non-homesteader leg is a loss, so
            # each leg is weighted separately (see `vectors`).
            gain_hs, gain_no, w = m._he_legs(p["dex"], p["mp"], p["label"])
            gaining = float((W * w * (gain_hs > 0)).sum()
                            + (W * (1 - w) * (gain_no > 0)).sum())
            losing = float((W * w * (gain_hs < 0)).sum()
                           + (W * (1 - w) * (gain_no < 0)).sum())
            desc = "exemption +$%s, mill %+.2f%%" % (format(p["dex"], ","), 100 * p["mp"])
        elif sc.family == "PTFC":
            p = sc.build(m)
            delta = E.credit(m.df, p["params"]) - m.base
            state = delivered = m.real_puma(p["params"])
            gaining = float(W[delta > 0].sum())
            losing = float(W[delta < 0].sum())
            desc = p["desc"]
        else:
            if rd is None:
                rd = C.Redesign(m) if redesign is None else redesign
            d = sc.build(rd)
            pr = rd.profile(d)
            state = delivered = pr["cost_m"] * 1e6
            gaining = pr["households_gaining"]
            # A ceiling is a greater-of against current law, so it cannot take
            # anything away. Nobody loses on 7 or 8 by construction.
            losing = 0.0
            desc = d.name.split(":", 1)[1].strip() if ":" in d.name else d.name
        rows.append(dict(id=sc.id, scenario=sc.name, family=sc.family,
                         lever=sc.lever, parameter=desc,
                         state_cost=state, delivered=delivered,
                         households_gaining=gaining, households_losing=losing))
    return pd.DataFrame(rows)
