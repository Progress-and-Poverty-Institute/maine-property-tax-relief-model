#!/usr/bin/env python3
"""Scenario 14: Homestead Plus.

Models *Homestead Plus: A Proposal for Property Tax Reform* (discussion draft,
June 2026), an outside proposal the Task Force asked to have evaluated.

WHAT THE SCENARIO IS
--------------------
1. Revenue Sharing I and II, the homestead reimbursement and the PTFC are all
   abolished and redirected, as the draft proposes. Pool: $475.4M.
2. The homestead exemption itself is abolished, not merely unreimbursed, so the
   $7.30B of exempt value returns to the municipal tax base.
3. The PTFC is replaced for owners and renters by a tiered circuit breaker.
   Renters' counted tax stays 15% of contract rent, as in 36 M.R.S. 5219-KK.
4. Take-up is held at today's PTFC claiming rate, as in every other scenario.

THE SCHEDULE: `ptfc_engine.HP_CANONICAL`, brackets at 2 / 3 / 5 / 8% of income
with State shares 0 / 50 / 80 / 85 / 90%, spending $465.8M.

WHY THE DRAFT'S SCHEDULE IS NOT USED AS IS
------------------------------------------
The draft's own schedule spends $157.8M of the $475.4M its own reform frees. The schedule pays nothing
below 4% of income and the median Maine owner pays 3.19%, rising to 3.74% once
the exemption goes, so the median owner is entitled to nothing. Only 46.8% of
owners clear 4% even after the reform.

The binding constraint is capacity, not generosity. At these bands, one
percentage point of State share is worth $6.91M in the 0-2% band and $4.65M in
2-6%, but only $0.88M and $0.85M in the two upper bands. The top two bands can
absorb at most $173M between them even at a 100% State share. Any schedule that
spends this pool must therefore reach well below a 4% burden.

WHY TAKE-UP IS NOT RAISED, THOUGH THE DRAFT PROPOSES AUTOMATIC DELIVERY
-----------------------------------------------------------------------
Automatic delivery needs MRS to hold both an income figure and a property tax
figure per household. MRS has income for filers. It has property tax only from
Schedule PTFC, and it receives no parcel-level property tax from municipalities
either: the MVR supplies homestead counts and values in aggregate per town
(Lines 14a-14f), not a parcel list. So the households automatic delivery would
reach are, by definition, the ones that did not supply the data it needs.
Requiring property tax to be reported on the Maine income tax return would
unlock it, but the draft does not propose that.

NO BURDEN CEILING
-----------------
The top band is 90%, not 100%, because the draft never exceeds 80% and its own
illustration leaves the taxpayer 20% of the marginal tax. The State's share
therefore approaches but never reaches its top rate, so a household's residual
burden climbs without limit: at a 30% burden it still pays about 9% of income
after relief. This is a property of the proposal's design, not of the
calibration.

NOT MODELLED: BETR. It reimburses businesses for property taxes paid on
pre-2008 equipment and is paid to the taxpayer rather than the municipality, so
it never enters the mill denominator the way BETE does. It does float with the
mill: a 7.16% rise raises every claim by 7.16%, roughly $1.2M on FY26's $16.8M
programme, or 0.25% of the pool. BETR is cut 50% from August 2026 and sunsets
with final payments due November 2027.

There is no other mill-linked municipal reimbursement: TRCF Line 6 equals Line 3
plus Line 4b plus Line 5b in all 494 towns, so Tree Growth, Farmland, Open Space
and the veterans' exemptions do not enter the denominator and do not float.
"""
import numpy as np
import pandas as pd

import ptfc_engine as E          # noqa: E402
import ptfc_takeup as T          # noqa: E402
import reallocation as RA        # noqa: E402
import fund_totals as F          # noqa: E402

# Per-town mill change with the exemption abolished and revenue sharing and the
# homestead reimbursement withdrawn.
FRAME = "s14_homestead_plus.csv"


def _puma_dmill(frame: pd.DataFrame) -> pd.Series:
    """Proportional mill change per PUMA, levy-weighted over all 494 towns."""
    f = frame.copy()
    f["key"] = T._key(f["Place"])
    f["dlevy"] = f["dmill"] * f["base"]
    full = RA._levy_frame().merge(f[["key", "dlevy"]], on="key", how="left")
    full["dlevy"] = full["dlevy"].fillna(0.0)
    g = T.to_puma(full, T.load_xwalk(), sum_cols=("levy", "dlevy")).groupby("PUMACE20")
    return (g["dlevy"].sum() / g["levy"].sum()).loc[T.PUMA_ORDER]


class HomesteadPlus:
    """Homestead Plus against the abolished exemption, at today's take-up."""

    def __init__(self, model, params: "E.HomesteadPlusParams" = E.HP_CANONICAL):
        self.m, self.params = model, params
        m = model

        self.dmill = _puma_dmill(pd.read_csv(RA.SCEN_DIR / FRAME))
        self.mp = np.array([self.dmill[q] for q in m.df["PUMA"].to_numpy()])

        # The exemption actually in effect is capped by the home's own value, so
        # abolishing it adds back min(value, $25,000), not a flat $25,000.
        hv = pd.to_numeric(m.df["home_value"], errors="coerce").to_numpy()
        self.exempt_eff = np.where(np.isnan(hv), 25_000.0,
                                   np.minimum(hv, 25_000.0))
        mill1 = m.mill_h * (1.0 + self.mp)     # exemption leg at the new mill
        self.bill_hs = np.where(m.owner,
                                m.tax0 * (1 + self.mp) + self.exempt_eff * mill1,
                                m.tax0 * (1 + self.mp))
        self.bill_non = m.tax0 * (1 + self.mp)
        self.share = m.hshare_h                # homestead coverage, a weight
        self.bills = np.where(m.owner,
                              self.share * self.bill_hs
                              + (1 - self.share) * self.bill_non,
                              self.bill_non)

        hp_hs = E.homestead_plus(m.df, params, prop_tax=self.bill_hs)
        hp_non = E.homestead_plus(m.df, params, prop_tax=self.bill_non)
        self.credit = np.where(m.owner,
                               self.share * hp_hs + (1 - self.share) * hp_non,
                               hp_non)
        self._hp_hs, self._hp_non = hp_hs, hp_non
        self.base_credit = E.credit(m.df, m.p0)        # current-law PTFC

        self.tau = np.asarray(m.tau_h, float)

    # ---------------------------------------------------------------- cost
    @property
    def pool(self) -> float:
        """What the State stops paying: revenue sharing, homestead
        reimbursement and the PTFC.

        The PTFC leg is take-up weighted at current rates, because that is what
        the State actually spends today.
        """
        # Homestead reimbursement: TRCF Line 21 ($85.4m in the 2024 MVR), as
        # Scenario 12. Revenue sharing: Rev I + Rev II ($264.6m in FY2025).
        return (RA.gross_pool("12") + F.revenue_sharing()["total"]
                + float((self.base_credit * self.m.W * np.asarray(self.m.tau_h, float)).sum()))

    @property
    def cost(self) -> float:
        return float((self.credit * self.m.W * self.tau).sum())

    # -------------------------------------------------------- distribution
    def net(self):
        """Per-household net gain: expected credit less the credit it replaces,
        less the change in the bill.

        Both credit legs are take-up weighted. The bill leg is not weighted at
        all: a homesteader loses the exemption whether or not anybody files.
        """
        tau0 = np.asarray(self.m.tau_h, float)
        return (self.credit * self.tau - self.base_credit * tau0
                - (self.bills - self.m.tax0))

    def _legs(self):
        """(homesteader net, non-homesteader net). Counting needs these.

        `net()` blends the two by PUMA homestead coverage, which is right for
        anything that sums and wrong for anything that counts: a household
        either holds a homestead or does not, and the blend can put an owner on
        the gaining side of zero when neither leg gains. Same distinction as
        `Model._he_legs()` for scenarios 1-3.
        """
        tau0 = np.asarray(self.m.tau_h, float)
        d_bill_hs = self.bill_hs - self.m.tax0
        d_bill_non = self.bill_non - self.m.tax0
        base = self.base_credit * tau0
        return (self._hp_hs * self.tau - base - d_bill_hs,
                self._hp_non * self.tau - base - d_bill_non)
