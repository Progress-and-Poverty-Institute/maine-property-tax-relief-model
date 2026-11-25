#!/usr/bin/env python3
"""Municipal mill rates under the reallocation scenarios (S9-S14).

Each scenario withdraws a State payment to municipalities: revenue sharing
(Rev I, Rev II) or the homestead exemption reimbursement. Every town then
re-solves its mill rate so that it still raises its budget. Writes one table per
scenario to data/derived/scenarios/.

The mill identity used throughout, per town:

    m1 * (B + r1*EV + BT) = m0 * (B + r0*EV + BT) + dRS

    B   taxable base (commitment / mill)
    EV  homestead exempt value; r0, r1 the reimbursement rate before and after
    BT  reimbursable BETE value (TRCF Line 22 / mill)
    dRS anticipated revenue sharing withdrawn

The reimbursement terms are a rate times a mill times a value, so they float
with the mill: when a town raises its rate, the State's homestead and BETE
reimbursements rise with it.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import paths  # noqa: E402
import ptfc_takeup as T  # noqa: E402

OLD_REIMB = 0.76     # current homestead reimbursement rate
LO, HI = 0.5, 1.5    # bounds on each town's anticipated-to-projected ratio


def norm(s):
    s = str(s).upper().strip()
    s = re.sub(r"\bST\.?\b", "SAINT", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def load_towns():
    """Municipal returns for the base year (ptfc_takeup.MVR_YEAR, 2024) joined to
    the revenue sharing projections (FY2025)."""
    mvr = pd.read_csv(paths.MVR)
    mvr = mvr[(mvr["Year"] == T.MVR_YEAR) & (mvr["Aggregation"] == "Muni")].copy()
    mvr["key"] = mvr["Place"].apply(norm)
    mvr["base"] = mvr["commitment"] / mvr["mill_rate"]
    base = mvr[["key", "Place", "mill_rate", "commitment", "base",
                "Expected RevShare", "TRCF: Line 21", "TRCF: Line 22"]].rename(
        columns={"mill_rate": "m0", "commitment": "commit",
                 "Expected RevShare": "l12", "TRCF: Line 21": "he_reimb",
                 "TRCF: Line 22": "bete_reimb"})
    # Reimbursable BETE value (TRCF Line 5b) is Line 22 divided by the mill: the
    # value the town adds to its tax base and the State reimburses at its mill
    # (MRS Property Tax Bulletin 28, section 6.D).
    base["bete_reimb"] = base["bete_reimb"].fillna(0.0)
    base["bete"] = (base["bete_reimb"] / base["m0"]).fillna(0.0)

    p = pd.read_excel(paths.REVENUE_SHARING_PROJECTIONS, header=5, engine="calamine")
    p.columns = [str(c).replace(chr(10), " ").strip() for c in p.columns]
    col_n = [c for c in p.columns if c.startswith("Total Projected")][0]
    col_i = [c for c in p.columns if c.startswith("Rev I Projected")][0]
    col_ii = [c for c in p.columns if c.startswith("Rev II Projected")][0]
    proj = (p[["Municipality Name", col_i, col_ii, col_n]]
            .dropna(subset=["Municipality Name"])
            .rename(columns={col_n: "proj", col_i: "revI", col_ii: "revII"}))
    proj["key"] = proj["Municipality Name"].apply(norm)
    proj = proj[proj["proj"].apply(lambda x: isinstance(x, (int, float)) and not pd.isna(x))]
    for c in ("revI", "revII"):
        proj[c] = pd.to_numeric(proj[c], errors="coerce").fillna(0.0)

    d = base.merge(proj[["key", "revI", "revII", "proj"]], on="key", how="left")
    matched = d["proj"].notna()      # unorganised territories have no projection
    print(f"{len(d)} municipalities, {matched.sum()} matched to the projections")
    return d, matched


def revshare_loss(df, remove):
    """Anticipated revenue sharing a town loses when Rev I, Rev II or both go to zero.

    A town's anticipated revenue sharing (MVR Line 12) is scaled down in
    proportion to its projected payment. Four towns left Line 12 blank although
    they receive revenue sharing; their anticipated amount is imputed at the
    median ratio of the towns that reported it.
    """
    l12, proj = df["l12"], df["proj"]
    removed = {"I": df["revI"], "II": df["revII"],
               "both": df["revI"] + df["revII"]}[remove]
    proj_new = (proj - removed).clip(lower=0)
    blank = (l12 == 0) & (proj > 0)
    r_obs = (l12 / proj.where(proj > 0)).clip(LO, HI)
    r_med = float(r_obs[(~blank) & (proj > 0)].median())
    r = r_obs.where(~blank, r_med).fillna(r_med)
    l12_eff = l12.where(~blank, r * proj)
    return (l12_eff - r * proj_new).clip(lower=0)


def he_reimb_loss(df, new_rate):
    """Reimbursement a town loses when the homestead rate falls from 76%, exemption held."""
    ev = df["he_reimb"] / (OLD_REIMB * df["m0"])
    m1 = df["m0"] * (df["base"] + OLD_REIMB * ev) / (df["base"] + new_rate * ev)
    return (df["he_reimb"] - new_rate * ev * m1).clip(lower=0)


def new_mill(df, d_rs, new_rate):
    """The town's re-solved mill rate (see the identity in the module docstring)."""
    ev = (df["he_reimb"] / (OLD_REIMB * df["m0"])).fillna(0.0)
    bt = df["bete"]
    return ((df["m0"] * (df["base"] + OLD_REIMB * ev + bt) + d_rs)
            / (df["base"] + new_rate * ev + bt))


def write(df, freed, d_rs, new_rate, name):
    out = df[["Place", "commit", "m0", "base", "l12", "he_reimb", "bete",
              "revI", "revII", "proj"]].copy()
    m1 = new_mill(df, d_rs, new_rate)
    dm = m1 - df["m0"]
    out["dL"] = np.asarray(freed)
    out["mill1"] = m1.values
    out["dmill"] = dm.values * 1000                      # mills
    out["dmillpct"] = 100 * dm.values / df["m0"].values  # percent of the rate
    out.to_csv(paths.SCENARIO_DIR / f"{name}.csv", index=False)
    print(f"{name:32s} freed ${out['dL'].sum() / 1e6:6.1f}m   "
          f"average mill change {100 * average_change(out):+.2f}%")


def average_change(out):
    """The statewide mill change, on the one measure the model reports."""
    return T.levy_weighted(pd.Series(out["dmillpct"].to_numpy() / 100,
                                     index=T._key(out["Place"]).to_numpy()))


def main():
    paths.SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    d, matched = load_towns()
    zero = pd.Series(0.0, index=d.index)

    # S9, S10: abolish Rev I or Rev II; the 76% reimbursement survives.
    for sid, comp, name in (("9", "I", "s9_abolish_rev_sharing_1"),
                            ("10", "II", "s10_abolish_rev_sharing_2")):
        m = d[matched].copy()
        loss = revshare_loss(m, comp)
        write(m, loss, loss, OLD_REIMB, name)

    # S11, S12: cut the homestead reimbursement; no revenue sharing withdrawn.
    for rate, name in ((0.50, "s11_homestead_reimb_50"), (0.0, "s12_homestead_reimb_0")):
        m = d.copy()
        write(m, he_reimb_loss(m, rate), zero.loc[m.index], rate, name)

    # S13: all three withdrawn; the exemption is kept but no longer reimbursed.
    m = d[matched].copy()
    rev = revshare_loss(m, "both")
    write(m, rev + he_reimb_loss(m, 0.0), rev, 0.0, "s13_all_three")

    # S14, Homestead Plus: the homestead exemption itself is abolished, so its
    # value returns to the taxable base, and revenue sharing is withdrawn too.
    m = d[matched].copy()
    ev = m["he_reimb"] / (OLD_REIMB * m["m0"])
    rev = revshare_loss(m, "both")
    out = m[["Place", "commit", "m0", "base", "bete"]].copy()
    out["EV"] = ev.values
    levy_add = rev + m["he_reimb"]
    mill1 = ((m["commit"] + levy_add + m["bete_reimb"])
             / (m["base"] + ev + m["bete"]))
    out["mill1"] = mill1.values
    out["dmill"] = (mill1 - m["m0"]).values * 1000
    out["dmillpct"] = 100 * (mill1 - m["m0"]).values / m["m0"].values
    out.to_csv(paths.SCENARIO_DIR / "s14_homestead_plus.csv", index=False)
    print(f"{'s14_homestead_plus':32s} average mill change {100 * average_change(out):+.2f}%")


if __name__ == "__main__":
    main()
