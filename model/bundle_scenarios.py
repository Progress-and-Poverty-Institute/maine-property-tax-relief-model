#!/usr/bin/env python3
"""All nineteen published scenarios, and any added in `local_scenarios`, behind
one accessor.

The scenarios come from four families (the homestead and PTFC changes in
`scenarios`, the revenue-neutral reallocations in `reallocation`, Homestead
Plus in `homestead_plus`, and the Task Force scenarios built on `task_force`),
each with its own call shape. `load()` returns them all as `Scen` objects so
nothing downstream needs to know which family a scenario came from.

`vec` is the per-household net gain in dollars: the extra credit a household
expects, less the extra property tax it pays. The credit leg is weighted by
take-up, because a household receives only what it claims; the bill leg is
not, because a higher mill rate is paid whether or not anyone files. That
asymmetry is why some reforms leave households worse off.

Counting is not summing. Scenarios that change the homestead exemption blend
the homesteader and non-homesteader outcomes by each PUMA's homestead
coverage, because PUMS carries no homestead flag. The blend is right for
anything that sums and wrong for anything that counts: testing a blended
expectation against zero would count more households gaining than there are
homesteads. `better()`, `worse()` and `histogram()` weight the two legs
separately wherever legs exist. Never count by testing `vec` directly.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

import ptfc_recalibrate as R
import scenarios as S
import reallocation as RA
import homestead_plus as HP
import fund_totals as F
import local_scenarios as LS

# A gain or loss smaller than this, in dollars, counts as no change. One
# threshold for every scenario, because the dashboard shows them in one table.
DEADBAND = 1.0

# The dollars-delivered histogram. The edges are fixed and shared by every
# scenario and every archetype subset so that panels are comparable. The middle
# bin is the deadband, so the histogram agrees with the better/worse counts:
# the positive bins sum to `better()` and the negative bins to `worse()`.
BIN_EDGES = (-np.inf, -1000.0, -500.0, -250.0, -100.0,
             -DEADBAND, DEADBAND,
             100.0, 250.0, 500.0, 1000.0, np.inf)
BIN_LABELS = ("worse off by more than $1,000",
              "worse off by $500 to $1,000",
              "worse off by $250 to $500",
              "worse off by $100 to $250",
              "worse off by up to $100",
              "no change",
              "better off by up to $100",
              "better off by $100 to $250",
              "better off by $250 to $500",
              "better off by $500 to $1,000",
              "better off by more than $1,000")

COST35 = [str(i) for i in range(1, 9)]
REALLOC = [str(i) for i in range(9, 15)]
# The five Task Force scenarios, S15-S19.
OCTOBER = ["15", "16", "17", "18", "19"]
# Scenarios added in local_scenarios.py (none as shipped).
LOCAL = [s.id for s in LS.check()]
ORDER = COST35 + REALLOC + OCTOBER + LOCAL
GROUP = {**{s: "cost35" for s in COST35}, **{s: "realloc" for s in REALLOC},
         **{s: "october" for s in OCTOBER}, **{s: LS.GROUP for s in LOCAL}}
GROUP_LABEL = {
    "cost35": "$35 million of new State spending",
    "realloc": "Revenue-neutral relief reallocation",
    "october": "Task Force scenarios",
    **({LS.GROUP: LS.GROUP_LABEL} if LOCAL else {}),
}


class Scen:
    """One scenario. `vec` sums; `better`/`worse` count."""

    __slots__ = ("id", "name", "group", "family", "parameter",
                 "state_cost", "pool", "delivered", "vec", "legs", "w",
                 "bills", "credit", "params", "exemption", "hplus", "tau",
                 "redirected", "split", "funding")

    def __init__(self, id, name, family, parameter, state_cost, pool, vec,
                 W, legs=None, w=None, bills=None, credit=None,
                 params=None, exemption=25_000.0, hplus=False, tau=None,
                 redirected=None, split=None, funding=None):
        self.id, self.name, self.family = id, name, family
        self.group = GROUP[id]
        self.parameter = parameter
        self.state_cost = float(state_cost)
        self.pool = float(pool)
        self.vec = np.asarray(vec, float)
        self.legs = legs
        self.w = w
        self.delivered = float((self.vec * W).sum())
        # The household-level view, for the narrow archetypes: each household's
        # property tax bill and total statutory credit under the scenario. Where
        # the scenario moves the homestead exemption this is the enrolled
        # homesteader leg, not the blend, because an archetypal household either
        # holds a homestead or does not. `vec` stays blended, for sums.
        self.bills = None if bills is None else np.asarray(bills, float)
        self.credit = None if credit is None else np.asarray(credit, float)
        # Enough to rebuild one household's outcome from scratch, for the
        # vignettes: the credit rules in force, the homestead exemption the
        # scenario leaves standing, and whether the credit is the PTFC or the
        # Homestead Plus schedule.
        self.params = params
        self.exemption = float(exemption)
        self.hplus = bool(hplus)
        # The claiming rate that applies to this scenario's credit: today's
        # PTFC take-up, except Homestead Plus, which carries its own
        # (homestead_plus.HomesteadPlus.tau).
        self.tau = None if tau is None else np.asarray(tau, float)
        # Packages only (S15-S19 and local packages): the State aid the package
        # takes from towns, Revenue Sharing I plus the reimbursement rate cut.
        self.redirected = None if redirected is None else float(redirected)
        # Scenarios 9-13 only: the shares of the credit expansion bought by the
        # maximum credits, the benefit bases and the income offset
        # (reallocation.Expansion.split).
        self.split = split
        # Packages only: where the money goes, in dollars a year. The Revenue
        # Sharing I cut, the change in the State's homestead and business
        # equipment reimbursements, and the extra credit. Not written to
        # dashboard.json; pipeline/09_report_figures.py prints it.
        self.funding = funding

    def _share(self, mask, W, sign):
        hi, lo = DEADBAND, -DEADBAND
        if self.legs is None:
            v = self.vec
            hit = (v > hi) if sign > 0 else (v < lo)
            return float(W[mask][hit[mask]].sum() / W[mask].sum())
        a, b = self.legs
        ha = (a > hi) if sign > 0 else (a < lo)
        hb = (b > hi) if sign > 0 else (b < lo)
        blend = self.w * ha + (1.0 - self.w) * hb
        return float((blend[mask] * W[mask]).sum() / W[mask].sum())

    def histogram(self, mask, W):
        """Weighted household counts per BIN_LABELS, over `mask`.

        Binning is counting, so it is leg-weighted wherever legs exist, as
        `better`/`worse` are: a blended expectation describes no actual
        household, and binning it would invent one that is partly a
        homesteader.
        """
        def hist(v, wt):
            idx = np.digitize(v[mask], BIN_EDGES[1:-1], right=False)
            return np.bincount(idx, weights=wt, minlength=len(BIN_LABELS))

        if self.legs is None:
            return [float(x) for x in hist(self.vec, W[mask])]
        a, b = self.legs
        wa = (self.w * W)[mask]
        wb = ((1.0 - self.w) * W)[mask]
        return [float(x) for x in (hist(a, wa) + hist(b, wb))]

    def better(self, mask, W):
        return self._share(mask, W, +1)

    def worse(self, mask, W):
        return self._share(mask, W, -1)


def _ptfc_param(p, p0):
    bits = []
    b = p.base_single / p0.base_single
    if abs(b - 1) > 1e-6:
        bits.append("benefit bases x%.4g" % b)
    c = p.cap_under65 / p0.cap_under65
    if abs(c - 1) > 1e-6:
        bits.append("maximum credit x%.4g" % c)
    if abs(p.rate_income - p0.rate_income) > 1e-9:
        bits.append("income offset %.4g%%" % (p.rate_income * 100))
    return ", ".join(bits) or "unchanged"


def load(model: "R.Model | None" = None) -> dict:
    """id -> Scen for every scenario in ORDER, on one Model."""
    m = R.Model() if model is None else model
    W = m.W.astype(float)
    out = {}

    import ptfc_engine as E
    import ceiling_redesign as C
    sl = S.build(m).set_index("id")
    vecs = S.vectors(m)
    tax0 = m.df["prop_tax"].to_numpy().astype(float)
    rd = None
    for sc in S.CANONICAL:
        legs = w = None
        if sc.family == "HE":
            p = sc.build(m)
            gh, gn, w = m._he_legs(p["dex"], p["mp"], p["label"])
            legs = (np.asarray(gh, float), np.asarray(gn, float))
            w = np.asarray(w, float)
            bill = m.he_bill(p["dex"], p["mp"], p["label"])
            bills = np.where(m.owner, bill, tax0)
            credit = m.base + m.delta(m.p0, bill)
            prm, exempt = m.p0, 25_000.0 + float(p["dex"])
        elif sc.family == "PTFC":
            bills = tax0
            prm = sc.build(m)["params"]
            credit = m.base + m.delta(prm)
            exempt = 25_000.0
        else:
            rd = C.Redesign(m) if rd is None else rd
            bills = tax0
            prm = sc.build(rd)
            credit = rd.credit(prm)
            exempt = 25_000.0
        row = sl.loc[sc.id]
        out[sc.id] = Scen(sc.id, str(row["scenario"]), sc.family,
                          str(row["parameter"]), float(row["state_cost"]),
                          0.0, vecs[sc.id], W, legs, w, bills, credit,
                          prm, exempt, tau=m.tau_h)

    for scn in RA.SCENARIOS:
        e = RA.Expansion(m, scn)
        r = e.solve()
        p = r["params"]
        out[scn] = Scen(scn, RA.SCENARIOS[scn][0], "REALLOC",
                        _ptfc_param(p, m.p0), 0.0, e.pool, e.net(p), W,
                        bills=e.bills,
                        credit=E.credit(m.df, p, e.bills),
                        params=p, exemption=25_000.0, tau=m.tau_h,
                        split=e.split(p))

    hp = HP.HomesteadPlus(m)
    n_hs, n_non = hp._legs()
    w14 = np.where(np.asarray(m.owner), np.asarray(hp.share, float), 0.0)
    thr = ", ".join("%.0f%%" % (t * 100) for t in hp.params.thresholds)
    rts = ", ".join("%.0f%%" % (x * 100) for x in hp.params.rates)
    out["14"] = Scen("14", "Homestead Plus", "HPLUS",
                     "burden thresholds %s; State share %s" % (thr, rts),
                     float(hp.cost - hp.pool), hp.pool, hp.net(), W,
                     (np.asarray(n_hs, float), np.asarray(n_non, float)), w14,
                     bills=np.where(m.owner, hp.bill_hs, hp.bill_non),
                     credit=hp._hp_hs,
                     params=hp.params, exemption=0.0, hplus=True,
                     tau=hp.tau)

    import task_force as CB
    # ---- The Task Force scenarios, S15-S19. Each takes money out of Revenue
    #      Sharing I and, in four of the five, out of the homestead reimbursement
    #      as well, then splits it between a larger Homestead Exemption and a
    #      wider Fairness Credit. The 4% income threshold never moves.
    #
    #      The maximum credit is a whole multiple of today's ($3,000/$4,000 in
    #      S15-S17, $3,750/$5,000 in S18) and the four benefit bases are rounded
    #      to the nearest $10, so the credit is fixed and the Revenue Sharing I
    #      cut is solved. A cut raises town mill rates, which raises bills, which
    #      raises both the reimbursement the State owes and the credit it pays,
    #      so the cut always exceeds the headline shortfall.
    #
    #      S16 and S17 share the same credit exactly. They differ only in the
    #      exemption, the reimbursement rate and the size of the cut, so the pair
    #      compares the exemption against the credit.
    def _revi_for(ex, rate, p_):
        """The Revenue Sharing I cut that leaves the State exactly whole under `p_`."""
        lo, hi = 0.0, F.revenue_sharing()["rev_i"]
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = ((lo, mid) if CB.Combo(m, exemption=ex, rate=rate,
                                            revi_cut=mid).fix(p_) < 0 else (mid, hi))
        return (lo + hi) / 2

    def _emit(sid, name, ex, rate, p_, cut, credit_desc, town_file=None):
        cb = CB.Combo(m, exemption=ex, town_file=town_file or "s%s_task_force.csv" % sid,
                      rate=rate, revi_cut=cut)
        st = cb.fix(p_)
        cb.write_towns()
        g_hs, g_no = cb.legs()
        bills_c = np.where(m.owner, cb.bill_hs, m.tax0)
        out[sid] = Scen(sid, name, "HE",
                        "Rev I -$%.1fm; reimbursement %d%%; exemption $%s; %s"
                        % (cut / 1e6, round(100 * rate), format(int(ex), ","), credit_desc),
                        round(float(st), 2) + 0.0, cb.ptfc_cost(p_), cb.vec(), W,
                        (np.asarray(g_hs, float), np.asarray(g_no, float)),
                        np.asarray(cb.w, float),
                        bills=bills_c, credit=CB.credit(m.df, p_, bills_c, m.p0),
                        params=p_, exemption=ex, tau=m.tau_h,
                        redirected=cb.redirected(),
                        funding=dict(revenue_sharing_cut=float(cut),
                                     homestead_reimbursement=float(cb.state["reimb"]),
                                     bete_reimbursement=float(cb.state["bete"]),
                                     credit=float(cb.ptfc_cost(p_))))

    BASES = ("base_single", "base_hoh_one", "base_joint_multi", "base_senior")
    for sid, name, ex, rate, ratio, mult in (
            ("15", "Exemption $40,000 at 50% reimbursement, maximum credit doubled",
             40_000.0, 0.50, 5.0, 2.0),
            ("16", "Exemption $30,000, reimbursement held at 76%, maximum credit doubled",
             30_000.0, 0.76, 4.0, 2.0),
            ("17", "Exemption doubled to $50,000 at 50% reimbursement, maximum credit doubled",
             50_000.0, 0.50, 4.0, 2.0),
            ("18", "Exemption $35,000 at 50% reimbursement, three quarters of the pool to the credit",
             35_000.0, 0.50, 3.5, 2.5)):
        t = (mult - 1.0) / ratio
        p_ = replace(CB.params(m.p0, t, ratio),
                     **{f: round(getattr(m.p0, f) * (1 + t) / 10.0) * 10.0 for f in BASES})
        _emit(sid, name, ex, rate, p_, _revi_for(ex, rate, p_),
              "benefit bases $%s; maximum credit $%s / $%s"
              % ("/$".join(format(int(getattr(p_, f)), ",") for f in BASES),
                 format(int(p_.cap_under65), ","), format(int(p_.cap_senior), ",")))

    # ---- S19. A two-tier credit with the exemption doubled, paid for out of
    #      Revenue Sharing I. The maximum binds exactly where the benefit base
    #      does, because 2,000 + 0.5 x (8,000 - 2,000) = 5,000, so neither
    #      parameter is redundant.
    wp = CB.TwoTierParams(**{f: getattr(m.p0, f) for f in m.p0.__dataclass_fields__},
                           tier1=2_000.0, tier2_rate=0.50, max_total=5_000.0, base_all=8_000.0)
    _emit("19", "Woodbury's two-tier credit with the exemption doubled, paid for out of "
                "Revenue Sharing I",
          50_000.0, 0.50, wp, _revi_for(50_000.0, 0.50, wp),
          "two-tier credit: 100% of tax above 4% of income to $2,000, then 50% to $5,000; "
          "benefit base $8,000 for every household, no age or dependency test")

    # ---- Scenarios added in local_scenarios.py, built the same two ways as the
    #      worked examples in docs/new-policy.md.
    for ls in LS.check():
        if isinstance(ls, LS.CreditChange):
            p_ = replace(m.p0, **ls.changes)
            d_ = m.delta(p_)
            out[ls.id] = Scen(ls.id, ls.name, "PTFC", LS.describe(ls.changes, m.p0),
                              m.real_puma(p_), 0.0, d_ * m.tau_h, W,
                              bills=tax0, credit=m.base + d_, params=p_,
                              exemption=25_000.0, tau=m.tau_h)
        else:
            p_ = replace(m.p0, **ls.credit)
            if ls.revi_cut is None:
                full = F.revenue_sharing()["rev_i"]
                if CB.Combo(m, exemption=ls.exemption, rate=ls.reimbursement,
                            revi_cut=full).fix(p_) > 0:
                    raise ValueError(f"local scenario {ls.id}: abolishing Revenue Sharing I "
                                     "would not pay for it; give revi_cut to fix the cut")
                cut = _revi_for(ls.exemption, ls.reimbursement, p_)
            else:
                cut = float(ls.revi_cut)
            _emit(ls.id, ls.name, ls.exemption, ls.reimbursement, p_, cut,
                  LS.describe(ls.credit, m.p0), town_file="s%s_local.csv" % ls.id)

    return {k: out[k] for k in ORDER}

