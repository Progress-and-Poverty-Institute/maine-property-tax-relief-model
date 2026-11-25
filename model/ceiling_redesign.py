"""
Scenarios 7 and 8: liability ceilings without cliffs, at $35m.

A liability ceiling pays the tax above a fixed share of income. Rationing it to
$35m with hard eligibility screens (S7: seniors 65+ below an income ceiling;
S8: home value <= $500,000) creates cliffs: one dollar of income or home value
over the line drops the household back to current law, and the drop is the
whole guarantee payment. The designs here ration the same budget smoothly,
inside one formula:

    credit = max( current-law credit ,
                  min( cap , max(0, counted_tax_eff - rate * Y) ) x phase-out(Y) )

    counted_tax_eff = counted_tax * min(1, V0 / home_value)   value apportionment

The max() against current law is part of the same formula: it reads "the
larger of your current credit or your tax above 6% of income".

S7 phases the guarantee out linearly over an income band (65+, no maximum).
S8 counts only the tax on the first V0 of home value (the Vermont rule), with
a maximum credit, for all ages.

Value caveat: home_value is PUMS VALP, the owner's own estimate, which runs
high against assessed just value (see ptfc_takeup). A value parameter
calibrated here is therefore in survey dollars; the statutory figure would be
set against assessed value and the certified ratio and would come out lower.
"""
from dataclasses import dataclass, asdict
import numpy as np

import ptfc_recalibrate as R     # noqa: E402

GROSS = R.GROSS


@dataclass
class Design:
    """One liability-ceiling design. Unset screens and caps are inactive."""
    name: str
    rate: float = 0.06
    seniors_only: bool = False
    income_ceiling: float = np.inf     # hard screen (S7)
    max_value: float = np.inf          # hard screen (S8)
    cap: float = np.inf                # maximum guarantee payment
    apportion: float | None = None     # V0: count tax on first V0 of value only
    gtaper: tuple | None = None        # (Y0, Y1): guarantee falls linearly to 0


class Redesign:
    """Scores ceiling designs against current law on the scenario model."""

    def __init__(self, model: "R.Model | None" = None):
        self.m = R.Model() if model is None else model
        c = R.Ceiling(self.m)
        self.T = c.crpt
        self.Y = np.maximum(c.income, 0.0)
        self.V = c.hv                     # 0 for renters
        self.senior = c.senior
        self.owner = self.m.owner
        self.base = self.m.base
        self.W, self.tau = self.m.W, self.m.tau_h

    # ------------------------------------------------------------ the credit
    def guarantee(self, d: Design) -> np.ndarray:
        T = self.T
        if d.apportion is not None:
            T = T * np.where(self.V > d.apportion, d.apportion / np.maximum(self.V, 1), 1.0)
        Y = self.Y
        cap = np.full_like(T, d.cap)
        g = np.minimum(cap, np.maximum(T - d.rate * Y, 0.0))
        if d.gtaper is not None:
            y0, y1 = d.gtaper
            g = g * np.clip((y1 - self.Y) / (y1 - y0), 0.0, 1.0)
        ok = self.Y <= d.income_ceiling
        if d.seniors_only:
            ok &= self.senior
        ok &= self.V <= d.max_value
        return np.where(ok, g, 0.0)

    def credit(self, d):
        return np.maximum(self.guarantee(d), self.base)

    def gain(self, d):
        """Delivered gain over current law, per household."""
        return (self.credit(d) - self.base) * self.tau

    def cost(self, d):
        return float((self.gain(d) * self.W).sum())

    def solve(self, d: Design, param: str, lo: float, hi: float) -> Design:
        """Bisect one field of `d` so the design costs GROSS."""
        def at(v):
            x = Design(**{**asdict(d), param: v})
            return x, self.cost(x)
        rising = at(hi)[1] > at(lo)[1]
        for _ in range(70):
            mid = (lo + hi) / 2
            if (at(mid)[1] < GROSS) == rising:
                lo = mid
            else:
                hi = mid
        return at((lo + hi) / 2)[0]

    # ------------------------------------------------------------- reading
    def cliff(self, d: Design, dY=1_000.0, dV=10_000.0):
        """Cliff test: the largest credit loss, and the households losing more
        than $500, from a small step in income or home value, among
        households the design currently pays."""
        base_g = self.credit(d)
        out = {}
        for lab, arr, step in (("income", "Y", dY), ("value", "V", dV)):
            saved = getattr(self, arr).copy()
            setattr(self, arr, saved + np.where(saved > 0, step, 0.0))
            try:
                from ptfc_engine import credit as _c  # current law ignores V; Y moves it
                if arr == "Y":
                    df = self.m.df.copy()
                    df["income"] = self.Y
                    base_step = _c(df, self.m.p0)
                    saved_base, self.base = self.base, base_step
                stepped = self.credit(d)
                if arr == "Y":
                    self.base = saved_base
            finally:
                setattr(self, arr, saved)
            loss = base_g - stepped
            paid = (base_g - self.base) > 1
            lp = loss[paid]
            wp = self.W[paid]
            out[f"worst loss per +${step:,.0f} {lab}"] = float(lp.max()) if lp.size else 0.0
            big = lp > 500
            out[f"hh losing >$500 per +${step:,.0f} {lab}"] = float(wp[big].sum())
        return out

    def profile(self, d: Design) -> dict:
        """Cost, reach, distribution and cliff measures for one design."""
        g = self.gain(d)
        W = self.W
        gw = g * W
        tot = gw.sum()
        inc = self.Y
        o = np.argsort(self.m.df["income"].to_numpy())
        cw = np.cumsum(W[o]) / W.sum()
        dec = np.empty(len(inc), int)
        dec[o] = np.clip((cw * 10).astype(int), 0, 9)
        dec += 1
        raw = self.credit(d) - self.base
        paid = raw > 1
        r = dict(
            design=d.name,
            cost_m=tot / 1e6,
            households_gaining=float(W[paid].sum()),
            renters_gaining=float(W[paid & ~self.owner].sum()),
            seniors_share_pct=100 * gw[self.senior].sum() / tot,
            bottom3_share_pct=100 * gw[dec <= 3].sum() / tot,
            top5_share_pct=100 * gw[dec >= 6].sum() / tot,
            value_over_500k_share_pct=100 * gw[self.V > 500_000].sum() / tot,
            value_over_750k_share_pct=100 * gw[self.V > 750_000].sum() / tot,
            max_payment=float(raw[paid].max()) if paid.any() else 0.0,
            hh_paid_over_5k=float(W[raw > 5_000].sum()),
            mean_payment=float((raw[paid] * W[paid]).sum() / W[paid].sum()),
        )
        # who it brings under the ceiling rate
        live = (self.Y > 0) & (self.T > 0)
        over = live & ((self.T - self.base) > d.rate * self.Y + 1e-6)
        fixed = over & ((self.T - self.credit(d)) <= d.rate * self.Y + 1e-6)
        r["above_rate_today"] = float(W[over].sum())
        r["brought_under"] = float(W[fixed].sum())
        r.update(self.cliff(d))
        return r


# ================================================================== designs
# Each scenario changes only the parameter it is about, holds every other
# parameter at the screened design's value, and solves the changed parameter to
# $35m. Solutions are searched on a round-number grid ($5,000 steps, fixed band
# width) and the grid point closest to $35m is taken.

def solve_band(rd: "Redesign", make, width, lo, hi, step=5_000):
    """Grid-search the lower edge of a phase-out band of fixed width so the
    design costs as close to GROSS as the grid allows. `make(y0, y1)` returns a
    Design. Returns (design, cost)."""
    best = None
    for y0 in range(int(lo), int(hi) + 1, int(step)):
        d = make(y0, y0 + width)
        c = rd.cost(d)
        if best is None or abs(c - GROSS) < abs(best[1] - GROSS):
            best = (d, c)
    return best


def adopted(rd: "Redesign"):
    """S7 and S8 with hard screens, each solved to $35m on one parameter.

    S7: 6%, 65+, no maximum, income <= a solved ceiling.
    S8: 6%, all ages, home value <= $500,000, maximum credit solved.

    `recommended()` takes Scenario 8's maximum credit from the S8 solved here.
    A hard screen moves cost in steps, so S7 lands near, not on, $35m."""
    s7 = rd.solve(Design("S7 screened", seniors_only=True), "income_ceiling", 20_000, 300_000)
    s8 = rd.solve(Design("S8 screened", max_value=500_000), "cap", 100, 20_000)
    s7.name = f"S7 screened: 65+, 6%, no max, income <= ${s7.income_ceiling:,.0f}"
    s8.name = f"S8 screened: 6%, value <= $500k, max ${s8.cap:,.0f}"
    return [s7, s8]


def recommended(rd: "Redesign"):
    """S7 and S8 with the cliff replaced, nothing else changed.

    S7 changes only the income rule: 6%, 65+, no maximum; the hard income
       screen becomes a $45,000 band over which the guarantee phases out,
       placed on a $5,000 grid to cost as close to $35m as possible.
    S8 changes only the value rule: 6%, all ages, and the maximum credit
       solved by `adopted`; the hard $500,000 screen becomes "only the tax on
       the first $X of value counts" (the Vermont rule), X on a $5,000 grid.
       At X = $500,000 the design costs well over $35m, so X is lower."""
    cap8 = adopted(rd)[1].cap
    s7, _ = solve_band(rd, lambda a, b: Design(
        f"REC S7: 65+, 6%, no max; guarantee phases out ${a/1e3:.0f}k-${b/1e3:.0f}k income",
        seniors_only=True, gtaper=(a, b)), 45_000, 50_000, 100_000)
    best = None
    for x in range(300_000, 500_001, 5_000):
        d = Design(f"REC S8: 6%, max ${cap8:,.0f}; only first ${x/1e3:.0f}k of value counts",
                   cap=cap8, apportion=x)
        c = rd.cost(d)
        if best is None or abs(c - GROSS) < abs(best[1] - GROSS):
            best = (d, c)
    return [s7, best[0]]

