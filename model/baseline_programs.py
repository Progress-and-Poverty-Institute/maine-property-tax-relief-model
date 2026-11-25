"""
Current relief programs measured against a world without them.

Every scenario is scored as a change from current law. This module scores the
two existing programs, the Property Tax Fairness Credit (PTFC) and the
Homestead Exemption, against a counterfactual in which they do not exist, so
the scenario results have a baseline to sit on.

FOUR WORLDS
-----------
    neither     no Homestead Exemption, no PTFC
    ptfc_only   PTFC on the bills households would face without the exemption
    he_only     today's bills, no PTFC
    both        current law (today's bills less the PTFC actually received)

The programs interact: the exemption lowers bills, which lowers the PTFC. So
the value of each program is reported two ways, standalone and net of the
other program's response.

HOMESTEAD EXEMPTION: TWO COSTINGS
---------------------------------
static   the exemption's value at today's mill rates, m0 x exempt value. This is
         the tax-expenditure number and the one usually quoted.
dynamic  each town re-solves its rate. Without the exemption the town's base
         grows by the exempt value, and it must raise the reimbursement it no
         longer receives from the State:
             m1 = (m0 x B + R) / (B + EV)
         Homesteaders' gain from the program is then m1 x gross value minus what
         they pay today; everyone else's is (m1 - m0) x their taxable value,
         which is negative. By construction the two sum to the reimbursement R:
         the State pays R, and the rest of what homesteaders receive is paid by
         other property through a higher mill rate.

The town-level accounting is exact from the Municipal Valuation Return (MVR,
lines 11, 12, 14e-14g). The household side has no homestead flag, town or
town rate, so it applies PUMA-level per-homestead values calibrated to
reproduce the MVR totals, with `homestead_share` as a probability weight as in
ptfc_recalibrate.

RENTERS
-------
The scenario model carries no renter incidence for mill changes. Here that
understates who pays for the exemption, so a sensitivity applies the PTFC
statute's own assumption (15% of rent is property tax) to the rate change.
It is reported separately and never folded into the headline.
"""
import numpy as np
import pandas as pd

import ptfc_engine as E          # noqa: E402
import ptfc_takeup as T          # noqa: E402
import ptfc_recalibrate as R     # noqa: E402
import congregate_care as CC     # noqa: E402

REIMB = 0.76                     # State share of the exemption's tax loss
RENT_SHARE = 0.15                # 36 M.R.S. 5219-KK: rent constituting property tax


def mrs_ty2024() -> dict:
    """MRS's TY2024 Fairness Credit claimants and dollars, summed from the
    by-town file after the withheld small-town claimants are allocated
    (ptfc_takeup.load_ptfc_town): the same totals the take-up rates divide.
    MRS's named-town subtotal, before that allocation, is 133,948 claimants
    and $113,102,190."""
    t = T.load_ptfc_town()
    return dict(claimants=float(t["n_ptfc"].sum()), paid=float(t["amt_ptfc"].sum()))


# ================================================================ town level
def town_accounting(year: int = T.MVR_YEAR) -> pd.DataFrame:
    """Who pays for the Homestead Exemption, town by town, from the MVR."""
    m = T.load_mvr(year)
    t = pd.DataFrame({
        "key": m["key"].to_numpy(), "county": m["county"].to_numpy(),
        "m0": m["mill_rate"].to_numpy(),
        "B": m["total_taxableval"].to_numpy(),          # line 11, after exemption
        "EV": m["hstead_eval"].to_numpy(),              # line 14f
        "HG": m["hstead_totalpval"].to_numpy(),         # line 14g, gross
        "n_hs": m["hstead_count"].to_numpy(),           # line 14e
    })
    t["Hb"] = t["HG"] - t["EV"]                         # homesteads' taxable value
    t["NB"] = t["B"] - t["Hb"]                          # everything else taxable
    t["R"] = REIMB * t["m0"] * t["EV"]
    t["m1"] = (t["m0"] * t["B"] + t["R"]) / (t["B"] + t["EV"])
    t["static_value"] = t["m0"] * t["EV"]
    t["hs_gain"] = t["m1"] * t["HG"] - t["m0"] * t["Hb"]
    t["other_gain"] = (t["m1"] - t["m0"]) * t["NB"]     # negative
    t["f"] = t["m1"] / t["m0"]                          # rate factor w/o exemption
    t["levy0"] = t["m0"] * t["B"]
    return t


def he_by_puma(town: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-homestead exemption value and the no-exemption rate factor, by PUMA."""
    town = town_accounting() if town is None else town
    cols = ("static_value", "hs_gain", "other_gain", "R", "n_hs", "levy0",
            "EV", "B", "NB")
    d = T.to_puma(town, T.load_xwalk(), sum_cols=cols)
    d["levy1"] = d["levy0"] * d["f"]
    g = d.groupby("PUMACE20")
    out = pd.DataFrame({
        "homesteads": g["n_hs"].sum(),
        "static_value": g["static_value"].sum(),
        "hs_gain": g["hs_gain"].sum(),
        "other_gain": g["other_gain"].sum(),
        "reimb": g["R"].sum(),
        # levy-weighted, as in he_mill_delta_by_puma: it scales observed bills
        "f": g["levy1"].sum() / g["levy0"].sum(),
    })
    out["x_static"] = out["static_value"] / out["homesteads"]
    return out.loc[T.PUMA_ORDER]


# =========================================================== household level
class Baseline:
    """The four worlds, per household, on the scenario model's population."""

    def __init__(self, model: "R.Model | None" = None, params=None):
        self.m = R.Model() if model is None else model
        self.p = self.m.p0 if params is None else params
        df = self.m.df
        self.W = self.m.W
        self.owner = df["owner"].to_numpy()
        self.tax0 = df["prop_tax"].to_numpy()
        self.rent = CC.rent_for_credit(df)   # occupancy portion, not the fee
        self.puma = df["PUMA"].to_numpy()
        self.tau = self.m.tau_h
        self.share = np.where(self.owner, self.m.hshare_h, 0.0)

        hp = he_by_puma()
        self.hp = hp
        # Exemption value per homestead, m0 x EV. A home worth less than $25,000
        # gets only a partial exemption, so each household's value is
        # proportional to min($25,000, home value), then rescaled within the
        # PUMA so the homestead-weighted total still reproduces the MVR.
        hv = pd.to_numeric(df["home_value"], errors="coerce").to_numpy()
        ex = np.where(self.owner, np.minimum(25_000.0, np.nan_to_num(hv, nan=0.0)), 0.0)
        self.x = np.zeros(len(df))
        for q in hp.index:
            s = self.puma == q
            wx = (self.share[s] * ex[s] * self.W[s]).sum()
            if wx > 0:
                self.x[s] = ex[s] * hp.loc[q, "static_value"] / wx
        self.f = np.array([hp["f"][q] for q in self.puma])          # m1 / m0

        # Bills without the exemption. Homestead branch: add the exemption back,
        # then the whole gross bill moves to the lower no-exemption rate.
        self.bill_hs_static = self.tax0 + self.x
        self.bill_hs_dyn = (self.tax0 + self.x) * self.f
        self.bill_no_dyn = self.tax0 * self.f              # non-homestead owners

    # ------------------------------------------------------------- pieces
    def ptfc(self, bill=None, delivered=True):
        c = E.credit(self.m.df, self.p, bill)
        return c * self.tau if delivered else c

    def _mix(self, a_hs, a_no):
        """Expected value over the unobserved homestead flag."""
        return self.share * a_hs + (1 - self.share) * a_no

    def worlds(self, dynamic=True, delivered=True, renter_passthrough=False):
        """Net property tax (bill less PTFC) per household in each world."""
        hs = self.bill_hs_dyn if dynamic else self.bill_hs_static
        no = self.bill_no_dyn if dynamic else self.tax0
        # renters: no bill in PUMS; optionally 15% of rent moves with the rate
        rent_tax0 = RENT_SHARE * self.rent
        rent_d = rent_tax0 * (self.f - 1) if (dynamic and renter_passthrough) else 0.0

        owner_or = lambda o, r: np.where(self.owner, o, r)  # noqa: E731
        bill_none_hs = owner_or(hs, self.tax0 + rent_d)
        bill_none_no = owner_or(no, self.tax0 + rent_d)
        today = self.tax0

        he_only = today
        neither = self._mix(bill_none_hs, bill_none_no)
        ptfc_now = self.ptfc(None, delivered)
        ptfc_none = self._mix(self.ptfc(bill_none_hs, delivered),
                              self.ptfc(bill_none_no, delivered))
        return pd.DataFrame({
            "neither": neither,
            "ptfc_only": neither - ptfc_none,
            "he_only": he_only,
            "both": today - ptfc_now,
            "ptfc_now": ptfc_now,
            "ptfc_none": ptfc_none,
        })

    def program_values(self, **kw) -> pd.DataFrame:
        """Per-household dollar value of each program (positive = gains)."""
        w = self.worlds(**kw)
        return pd.DataFrame({
            "PTFC": w["he_only"] - w["both"],                 # = PTFC received today
            "HE standalone": w["neither"] - w["he_only"],
            "HE net of PTFC": w["ptfc_only"] - w["both"],
            "Both programs": w["neither"] - w["both"],
        })

    # ------------------------------------------------------------- tables
    def totals(self):
        """Headline program totals, model vs administrative."""
        town = town_accounting()
        full = self.ptfc(None, delivered=False)
        dlv = self.ptfc(None, delivered=True)
        pv = self.program_values()
        pv_r = self.program_values(renter_passthrough=True)
        W = self.W
        p25 = Baseline(self.m, params=E.BASELINE)
        rows = [
            ("PTFC entitlement, full claiming (TY2026 law)", (full * W).sum()),
            ("PTFC delivered at PUMA take-up (TY2026 law)", (dlv * W).sum()),
            ("PTFC delivered at PUMA take-up (TY2025 law)", (p25.ptfc() * W).sum()),
            ("  MRS actual paid, TY2024", mrs_ty2024()["paid"]),
            ("PTFC recipients, delivered (TY2026 law)", (W * self.tau * (full > 0)).sum()),
            ("HE static value, m0 x exempt value (MVR)", town["static_value"].sum()),
            ("HE State reimbursement at 76% (MVR)", town["R"].sum()),
            ("HE dynamic: homesteaders' gain (MVR)", town["hs_gain"].sum()),
            ("HE dynamic: paid by other property via mill rate (MVR)", -town["other_gain"].sum()),
            ("HE static value, household side (PUMS, check)", (self.share * self.x * W).sum()),
            ("HE dynamic net to resident households (PUMS)", (pv["HE standalone"] * W).sum()),
            ("  of which: gain to homesteaders", (self.share * (self.bill_hs_dyn - self.tax0) * W).sum()),
            ("  of which: cost to owners w/o homestead", ((1 - self.share) * np.where(self.owner, self.bill_no_dyn - self.tax0, 0) * W).sum()),
            ("HE dynamic net, with 15%-of-rent pass-through", (pv_r["HE standalone"] * W).sum()),
            ("PTFC the exemption displaces (HE standalone - net)", ((pv["HE standalone"] - pv["HE net of PTFC"]) * W).sum()),
        ]
        return pd.DataFrame(rows, columns=["item", "dollars"])

