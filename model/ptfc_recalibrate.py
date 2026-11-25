"""
Scenario costing at measured PTFC take-up.

`Model` holds the PUMS population, its baseline Property Tax Fairness Credit
under TY2026 law, and a per-household take-up rate: the measured rate for the
household's PUMA (MRS claimants over PUMS-observed eligible households; see
`ptfc_takeup`). A reform's delivered cost is the change in each household's
credit, times its PUMA take-up rate, times its weight. Take-up varies a good
deal by PUMA, so applying one statewide rate would shift the solved parameters
of the multiplier levers by several percent.

Homestead Exemption relief is applied by the assessor automatically, so it is
not scaled by take-up. Take-up enters the Homestead scenarios only through the
PTFC clawback: a lower bill means a smaller credit, which the State no longer
pays.
"""
from dataclasses import replace
import re
import numpy as np
import pandas as pd

import ptfc_engine as E      # noqa: E402
import ptfc_takeup as T      # noqa: E402

GROSS = 35_000_000.0          # target net cost to the State
CEIL = 400.0                  # multiplier search ceiling

# Homestead Exemption scenarios, solved so the State's NET cost is $35M:
#
#   (exemption increase over $25,000, statewide mill change
#    (ptfc_takeup.levy_weighted, the measure reported everywhere),
#    gross homestead reimbursement cost, BETE reimbursement cost)
#
# Net cost is the homestead reimbursement plus the BETE reimbursement less the
# PTFC the State no longer pays because bills fell. The BETE reimbursement is the
# mill rate times exempt value, so it moves with the mill and is carried as its
# own leg; "gross" means the homestead reimbursement alone. Scenarios that raise
# the mill therefore cost more and solve to a smaller exemption; #2 lowers it.
#
# The values come from the municipal model in `he_resolve_net`, which pipeline
# step 03 runs and which also writes the per-scenario tables these labels key
# into. The labels must match `ptfc_takeup.HE_SCENARIO_FILES` character for
# character.
HE_SCENARIOS = {
    "#1 HE $36,600 @ 76%": (11_600, +0.00338, 39_474_366.3, 268_163.4),
    "#2 HE $27,600 @ 100%": (2_600, -0.00730, 37_252_941.9, -581_320.5),
    "#3 HE $56,400 @ 50%": (31_400, +0.02766, 43_777_034.4, 2_203_835.3),
}

CURRENT_EXEMPTION = 25_000.0

_HE_LABEL = re.compile(r"^(#\d) HE \$([\d,]+) @ (\d+)%$")


def he_canonical():
    """The Homestead scenarios as (id, label, exemption, reimbursement rate).

    The exemption amounts are defined here and nowhere else; anything that
    builds the municipal model at a scenario's exemption reads them from this
    function. Each label carries the exemption as text and the tuple carries it
    as an increment over $25,000, and the per-PUMA mill lookup keys on the label
    alone, so the two are checked against each other at import.
    """
    out = []
    for label, (dex, _mp, _gross, _bete) in HE_SCENARIOS.items():
        m = _HE_LABEL.match(label)
        if m is None:
            raise ValueError("HE_SCENARIOS label is not parseable: %r" % label)
        sid, e_txt, rate_txt = m.groups()
        E = float(e_txt.replace(",", ""))
        if abs(E - (CURRENT_EXEMPTION + dex)) > 0.5:
            raise ValueError(
                "%s: label says $%s but the tuple says $25,000 + $%s = $%s. "
                "Re-solve with he_resolve_net and update both together."
                % (sid, e_txt, format(int(dex), ","),
                   format(int(CURRENT_EXEMPTION + dex), ",")))
        out.append((sid, label, E, int(rate_txt) / 100.0))
    return out


he_canonical()          # fail at import, not at the call site


def baseline_params():
    """The scenario baseline: TY2026 law."""
    return E.TY2026


def scale_bases(k: float, p0=None):
    """Scenario 4 parameters: every benefit base multiplied by `k`.

    The multiplier is applied to the baseline's own bases, so "bases x k" means
    k times current law.
    """
    p0 = baseline_params() if p0 is None else p0
    s, h, j, sen = (p0.base_single, p0.base_hoh_one,
                    p0.base_joint_multi, p0.base_senior)
    return replace(p0, base_single=s*k, base_hoh_one=h*k,
                   base_joint_multi=j*k, base_senior=sen*k)


class Model:
    """Holds the population, the baseline credit, and per-household take-up."""

    def __init__(self, pums=None, takeup=None):
        self.df = T.load_pums() if pums is None else pums
        self.W = self.df["WGTP"].to_numpy()
        self.p0 = baseline_params()
        self.base = E.credit(self.df, self.p0)
        t = T.takeup_by_puma() if takeup is None else takeup
        rate = (t["takeup_pct"] / 100).to_dict()
        # Take-up varies by PUMA and by nothing else. In particular it does not
        # vary with income, so two eligible households in the same PUMA on $20k
        # and $90k are treated as equally likely to claim. The PTFC must be
        # claimed on a filed return, and filing becomes more likely as income
        # rises, so take-up probably rises with income. If it does, scenarios
        # that concentrate relief higher up the income scale are understated,
        # and the equal-cost comparison holds only to the extent that take-up is
        # independent of income. Resolving this would need MRS claimant counts
        # by income band.
        self.tau_h = np.array([rate[q] for q in self.df["PUMA"].to_numpy()])
        self.owner = self.df["owner"].to_numpy()
        self.tax0 = self.df["prop_tax"].to_numpy()
        # Home value not yet exempted: the cap on any exemption increase. VALP is
        # market (just) value and the exemption is stated in just value, so no
        # certified-ratio adjustment is needed here -- the ratio sits inside
        # mill_fv. VALP runs high, so this slightly under-corrects.
        hv = pd.to_numeric(self.df["home_value"], errors="coerce").to_numpy()
        self.room_h = np.maximum(np.nan_to_num(hv, nan=0.0) - 25_000.0, 0.0)
        # Homestead geography: per-household coverage and full-value rate, and
        # the per-scenario rate change, all at PUMA level (see ptfc_takeup).
        hp = T.homestead_by_puma()
        puma = self.df["PUMA"].to_numpy()
        self.hshare_h = np.array([hp["homestead_share"][q] for q in puma])
        self.mill_h = np.array([hp["mill_fv"][q] for q in puma])
        self.he_dmill = T.he_mill_delta_by_puma()

    # -------------------------------------------------------------- costing
    def delta(self, params, prop_tax=None):
        """Per-household change in the credit against the baseline."""
        return E.credit(self.df, params, prop_tax) - self.base

    def real_puma(self, params, prop_tax=None):
        """Delivered cost, each household at its own PUMA's take-up rate."""
        return float((self.delta(params, prop_tax) * self.tau_h * self.W).sum())

    def tau_flat(self):
        """Eligible-weighted mean take-up: the scalar equivalent of tau_h.

        Equals MRS claimants over PUMS-observed eligible households, so it
        tracks any change to the eligibility definition.
        """
        el = self.base > 0
        return float(np.average(np.asarray(self.tau_h, float)[el],
                                weights=self.W[el]))

    # ------------------------------------------------------------ solving
    def solve_multiplier(self, lo=0.001, hi=CEIL):
        """Benefit-base multiplier that reaches GROSS, or None if the lever
        saturates below it."""
        f = self.real_puma
        if f(scale_bases(hi)) < GROSS:
            return None
        for _ in range(90):
            m = (lo + hi) / 2
            if f(scale_bases(m)) < GROSS:
                lo = m
            else:
                hi = m
        return (lo + hi) / 2

    def solve_offset(self, cap_u65, cap_senior, lo=0.0, hi=0.04):
        """Income offset that reaches GROSS at the given caps. Cost is
        decreasing in the offset."""
        f = self.real_puma

        def cost(r):
            return f(replace(self.p0, rate_income=r,
                             cap_under65=cap_u65, cap_senior=cap_senior))

        if cost(lo) < GROSS:
            return None
        for _ in range(90):
            m = (lo + hi) / 2
            if cost(m) > GROSS:
                lo = m
            else:
                hi = m
        return (lo + hi) / 2

    # ------------------------------------------------- homestead scenarios
    def _geo(self, label):
        """Per-household (mill change, full-value rate, homestead share) for
        the Homestead scenario `label`, all at PUMA level."""
        dm = self.he_dmill[label]
        puma = self.df["PUMA"].to_numpy()
        return (np.array([dm[q] for q in puma]), self.mill_h, self.hshare_h)

    def he_bill(self, d_exempt, mill_pct, label=None):
        """Post-reform property tax. The bill itself is observed; only the change
        is modelled. Two legs, different in kind:

          mill leg       proportional, applied straight to the reported bill.
          exemption leg  a FLAT dollar amount, d_exempt x full-value rate, the
                         same for every homesteader in a town whatever their
                         bill. That flatness is the exemption's progressivity.

        The mill change applied is the per-PUMA change stored for `label`;
        `mill_pct`, the statewide figure, is not used. Renters carry only the
        mill change, which is zero in PUMS because renters have no prop_tax;
        renter incidence is not quantified."""
        mp, mill, _ = self._geo(label)
        # A household cannot exempt more than its home is worth, so the increase
        # is limited to the value the current $25,000 has not already exempted.
        # The fiscal side applies the same cap.
        d_eff = np.minimum(d_exempt, self.room_h)
        return np.where(self.owner,
                        np.maximum(self.tax0 * (1 + mp) - d_eff * mill, 0.0),
                        self.tax0 * (1 + mp))

    def he_delivered(self, d_exempt, mill_pct, label=None):
        """Per-household delivered benefit, net of the PTFC clawback.

        The two legs are scaled DIFFERENTLY. PUMS carries no homestead flag, so
        `share` is a probability weight rather than a partition:

          exemption leg  scaled by `share`. Only homesteaders receive it, and
                         weighting every owner by the share reproduces the
                         correct aggregate.
          mill leg       NOT scaled. Every owner pays the higher rate whether or
                         not they hold a homestead.

        The ~117,919 owner-occupiers without a homestead (PUMS owner-occupied
        minus MVR homesteads) therefore bear the rate rise and get nothing back.
        They lose under scenarios 1 and 3 and gain under 2.
        """
        gain_hs, gain_no, w = self._he_legs(d_exempt, mill_pct, label)
        return w * gain_hs + (1.0 - w) * gain_no

    def _he_legs(self, d_exempt, mill_pct, label=None):
        """(gain_hs, gain_no, w): the two legs and the homestead weight, unblended.

        Because `share` is a probability weight rather than a partition,
        anything that counts households, rather than summing dollars, must
        weight the legs separately. Blending first and then testing `> 0` counts
        every owner whose EXPECTATION is positive, which overstates the number
        of gaining households by more than a hundred thousand under scenarios 1
        and 3, where non-homesteaders lose."""
        _, _, share = self._geo(label)
        with_hs = self.he_bill(d_exempt, mill_pct, label)       # mill + exemption
        no_hs = self.he_bill(0.0, mill_pct, label)              # mill only
        gain_hs = (-(with_hs - self.tax0)) + self.delta(self.p0, with_hs) * self.tau_h
        gain_no = (-(no_hs - self.tax0)) + self.delta(self.p0, no_hs) * self.tau_h
        w = np.where(self.owner, share, 0.0)      # renters never hold a homestead
        return gain_hs, gain_no, w


# ===================================================================== ceilings
# Liability ceilings (scenarios 7 and 8) state an outcome -- no covered
# household pays more than a set share of income in property tax -- and pay
# what reaching it costs. They are layered on current law as a GREATER-OF, so
# no household can lose. The designs are defined in `ceiling_redesign`; this
# class supplies the per-household inputs.


def _counted_tax(df, p) -> np.ndarray:
    """Property tax that counts toward the credit: bill + 15% of counted rent.

    Counted rent is the occupancy portion, which differs from the reported fee
    only for congregate care; see congregate_care.py.
    """
    import congregate_care as CC
    return (df["prop_tax"].to_numpy()
            + p.rate_rent * CC.rent_for_credit(df))


class Ceiling:
    """Per-household inputs for a liability ceiling: counted tax, income, home
    value and age, from a Model's population."""

    def __init__(self, model: "Model"):
        self.m = model
        self.crpt = _counted_tax(model.df, model.p0)
        self.income = model.df["income"].to_numpy()
        # renters have no home value; nan means "not an owner", never "over cap"
        self.hv = np.nan_to_num(
            pd.to_numeric(model.df["home_value"], errors="coerce").to_numpy(),
            nan=0.0)
        self.senior = model.df["senior"].to_numpy()


# ------------------------------------------------------------- scenario 6
# Scenario 6 scales the caps and the benefit bases by separate multipliers.
# The two parameters do different jobs and reach different households: raising
# a cap pays households already at the maximum, while raising a base extends
# eligibility upward. Scenario 6 fixes the cap multiplier and solves the base
# multiplier with `solve_hybrid_base`.


def hybrid(cap_mult, base_mult, p0=None):
    """Baseline parameters with the caps scaled by `cap_mult` and the benefit
    bases by `base_mult`."""
    p0 = baseline_params() if p0 is None else p0
    s, h, j, sen = (p0.base_single, p0.base_hoh_one,
                    p0.base_joint_multi, p0.base_senior)
    return replace(p0,
                   cap_under65=p0.cap_under65 * cap_mult,
                   cap_senior=p0.cap_senior * cap_mult,
                   base_single=s * base_mult, base_hoh_one=h * base_mult,
                   base_joint_multi=j * base_mult, base_senior=sen * base_mult)


def solve_hybrid_base(model, cap_mult, lo=0.5, hi=CEIL):
    """Base multiplier that reaches GROSS at a given cap multiplier: one point
    on the Scenario 4 / 6 frontier. cap_mult=1 is Scenario 4."""
    f = model.real_puma
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(hybrid(cap_mult, mid)) < GROSS:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
