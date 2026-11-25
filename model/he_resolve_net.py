#!/usr/bin/env python3
"""Solve the homestead exemption scenarios (S1-S3) to a net State cost of $35m.

Each scenario raises the homestead exemption above $25,000 at a given State
reimbursement rate. The State's net cost has three parts:

    net(E) = gross homestead reimbursement change
           + BETE reimbursement change (the mill moves, so does BETE)
           + change in PTFC paid (credits shrink as bills fall)

The last term matters because a larger exemption lowers property tax bills and
the Property Tax Fairness Credit is computed from those bills, so part of the
exemption's cost comes back to the State as smaller credits. The municipal
model (MVR) supplies the mill-rate change; the household model (PUMS) supplies
the credit change. The exemption is bisected until net(E) = $35m.

The solved exemptions must equal those in ptfc_recalibrate.HE_SCENARIOS, which
the rest of the model reads; main() asserts this and writes one municipal table
per scenario.
"""
import json

import numpy as np
import pandas as pd

import paths
import ptfc_takeup as T           # noqa: E402
import ptfc_recalibrate as R      # noqa: E402

TARGET = 35_000_000.0              # net State cost each scenario is solved to
CURRENT_EXEMPTION = 25_000.0

# Value cap: a homestead cannot be exempted above its own just value, so raising
# the exemption past a home's value stops adding exempt value. Empirical
# distribution of owner-occupied just values, from licensed ATTOM property
# records, as summary counts only (data/derived/home_value_counts.json): counts
# in $1,000 bands from $25,000 to $100,000 (_CAP_COUNTS, at midpoints
# _CAP_MIDS), the count at $100,000 and above (_CAP_TAIL) and the total
# (_CAP_N). tools/home_value_counts.py rebuilds the file from any list of
# owner-occupied home values, such as a parcel extract; see value_cap_counts().
#
# In the shipped counts _CAP_N is 37 homes smaller than the bands plus the tail
# (150,414 against 150,451), as in the original extract, so cap_ratio(25,000)
# is 1.00025 rather than exactly 1. A rebuilt file has the two equal.
_CAP = json.loads(paths.HOME_VALUE_COUNTS.read_text())
_CAP_N, _CAP_TAIL = _CAP["n"], _CAP["at_or_above_100000"]
_CAP_COUNTS = np.array(_CAP["counts"])
_CAP_MIDS = np.arange(25_500, 100_000, 1000)


def value_cap_counts(values, weights=None) -> dict:
    """Rebuild the value-cap counts from owner-occupied homestead just values.

    `values` holds one just (market) value per home, in dollars; `weights` is
    optional (one per home). Homes under $25,000 are left out, because the
    current exemption already exempts a home only up to its value. Returns the
    dict stored in data/derived/home_value_counts.json.
    """
    v = np.asarray(values, float)
    w = np.ones_like(v) if weights is None else np.asarray(weights, float)
    keep = np.isfinite(v) & np.isfinite(w) & (v >= 25_000)
    v, w = v[keep], w[keep]
    body = v < 100_000
    counts, _ = np.histogram(v[body], bins=np.arange(25_000, 100_001, 1_000), weights=w[body])
    as_num = (lambda x: int(round(x))) if weights is None else float
    return dict(
        description=("Owner-occupied homes by just value: counts in $1,000 bands "
                     "from $25,000 to $100,000, the count at $100,000 and above, "
                     "and the total. Used by he_resolve_net.cap_ratio()."),
        band_from=25_000, band_width=1_000,
        counts=[as_num(c) for c in counts],
        at_or_above_100000=as_num(w[~body].sum()),
        n=as_num(w.sum()),
    )


def cap_ratio(E):
    """Share of a nominal exemption E that is actually exempted, statewide,
    after capping each homestead's exemption at its own just value."""
    body = float((np.minimum(E, _CAP_MIDS) * _CAP_COUNTS).sum())
    tail = min(E, 100_000.0) * _CAP_TAIL
    return (body + tail) / (E * _CAP_N)


def load_mvr():
    """Municipal rows of the Municipal Valuation Return for the model's base year
    (ptfc_takeup.MVR_YEAR, 2024), with the current
    commitment, homestead and BETE reimbursements, and reimbursable BETE value."""
    df = pd.read_csv(paths.MVR, low_memory=False)
    df = df[(df["Year"] == T.MVR_YEAR) & (df["Aggregation"] == "Muni")].copy()
    for c in ("certified_ratio", "mill_rate", "total_taxableval", "hstead_max_count",
              "hstead_part_val", "hstead_eval", "TRCF: Line 21", "TRCF: Line 22"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["certified_ratio", "mill_rate", "total_taxableval"]).copy()
    df["cur_MillRate"] = df["mill_rate"]
    df["cur_TaxableValue"] = df["total_taxableval"]
    df["cur_Commitment"] = df["cur_MillRate"] * df["cur_TaxableValue"]
    df["cur_HE_Reimb"] = df["TRCF: Line 21"].fillna(0)
    df["cur_BETE_Reimb"] = df["TRCF: Line 22"].fillna(0)
    df["cur_NetToBeRaised"] = df["cur_Commitment"] + df["cur_HE_Reimb"] + df["cur_BETE_Reimb"]
    # TRCF Line 5b: the REIMBURSABLE portion of BETE-exempt value. The town adds
    # it to its tax base when it sets the mill (MRS Property Tax Bulletin 28,
    # section 6.D) and the State reimburses it at that mill (36 M.R.S. 694(2)).
    # Derived as Line 22 / mill; this matches the MVR's own Line 5b in all 494
    # towns to within $0.02. The applicable percentage (50%, or 50% + half the
    # personal property factor, or a TIF rate) is already inside it, so nothing
    # here needs to model that percentage.
    df["cur_BETE_Value"] = (df["cur_BETE_Reimb"] / df["cur_MillRate"]).fillna(0.0)
    return df


def he_model(mvr, E, rate):
    """Each town's re-solved mill rate and State reimbursements at exemption E
    and homestead reimbursement rate `rate`, holding the amount to be raised."""
    exempt = (mvr["hstead_max_count"] * E * mvr["certified_ratio"] * cap_ratio(E)
              + mvr["hstead_part_val"].fillna(0))
    reimbval = rate * exempt
    taxable = mvr["cur_TaxableValue"] + mvr["hstead_eval"] - exempt
    # TRCF Line 6: the town funds its budget from taxable value plus BOTH
    # reimbursable portions, because both reimbursements are the mill times a
    # value and so rise with the mill. Holding BETE at the old mill instead
    # would make the town raise the difference itself and understate what the
    # State pays.
    mill = mvr["cur_NetToBeRaised"] / (taxable + reimbval + mvr["cur_BETE_Value"])
    return pd.DataFrame({
        "Place": mvr["Place"].values,
        "County": (mvr["County_ofMuni"] if "County_ofMuni" in mvr.columns
                   else mvr["County"]).values,
        "taxable": taxable.values, "mill": mill.values,
        "he_reimb": (reimbval * mill).values,
        "bete_reimb": (mvr["cur_BETE_Value"] * mill).values,
        "commitment": (mill * taxable).values,
        "mill_delta": (mill - mvr["cur_MillRate"]).values,
    })


def gross_cost(mvr, E, rate):
    """Change in the State's homestead reimbursement."""
    return he_model(mvr, E, rate)["he_reimb"].sum() - mvr["cur_HE_Reimb"].sum()


def bete_cost(mvr, E, rate):
    """Extra BETE reimbursement the State pays because the mill moved.

    No scenario changes BETE itself, so this is always at the municipality's
    own applicable percentage, which cur_BETE_Value already carries. Positive
    when the mill rises, negative when it falls.
    """
    return he_model(mvr, E, rate)["bete_reimb"].sum() - mvr["cur_BETE_Reimb"].sum()


def puma_dmill(mvr, xw, E, rate):
    """Per-PUMA proportional mill change, levy-weighted: sum(dmill x taxable) /
    sum(mill x taxable). Same basis as ptfc_takeup.he_mill_delta_by_puma()."""
    s = he_model(mvr, E, rate)
    s["key"] = T._key(s["Place"])
    s["county"] = T._county(s["County"])
    s["levy"] = s["mill"] * s["taxable"]
    s["dlevy"] = s["mill_delta"] * s["taxable"]
    g = T.to_puma(s, xw, sum_cols=("levy", "dlevy")).groupby("PUMACE20")
    return g["dlevy"].sum() / g["levy"].sum()


def net_cost(m, mvr, xw, E, rate):
    """(net, gross, bete, displaced) State cost at exemption E.

    `displaced` is the change in PTFC delivered when each household's bill
    moves: by the PUMA mill change for everyone, less the exemption increase
    (capped at the home's value above $25,000) at the full-value rate for
    owners. It is weighted by take-up, homestead coverage and survey weight.
    """
    gross = gross_cost(mvr, E, rate)
    bete = bete_cost(mvr, E, rate)
    dm = puma_dmill(mvr, xw, E, rate)
    mp = np.array([dm[q] for q in m.df["PUMA"].to_numpy()])
    d_eff = np.minimum(E - CURRENT_EXEMPTION, m.room_h)
    new = np.where(m.owner,
                   np.maximum(m.tax0 * (1 + mp) - d_eff * m.mill_h, 0.0),
                   m.tax0 * (1 + mp))
    displaced = float((m.delta(m.p0, new) * m.tau_h * m.hshare_h * m.W).sum())
    return gross + bete + displaced, gross, bete, displaced


def solve(m, mvr, xw, rate):
    """Exemption, to the nearest $100, at which net State cost is TARGET.

    Net cost rises with the exemption from $25,000 and, once past TARGET,
    stays above it up to the bracket's upper end, so bisection finds the one
    crossing.
    """
    lo, hi = CURRENT_EXEMPTION, 250_000.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if net_cost(m, mvr, xw, mid, rate)[0] < TARGET:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), -2)


def main():
    """Self-test, solve S1-S3, check them against HE_SCENARIOS, write tables."""
    mvr = load_mvr()
    xw = T.load_xwalk()
    m = R.Model()

    # At the current exemption and rate nothing changes, so neither the
    # homestead nor the BETE reimbursement may move.
    sq = gross_cost(mvr, CURRENT_EXEMPTION, 0.76)
    assert abs(sq) < 5e5, f"status-quo self-test failed: ${sq:,.0f}"
    sb = bete_cost(mvr, CURRENT_EXEMPTION, 0.76)
    assert abs(sb) < 5e3, f"BETE status-quo self-test failed: ${sb:,.0f}"
    print(f"self-test: homestead reimbursement change with no change in law = ${sq:,.0f}"
          f"  (passes if under $500,000, on $85m)")
    print(f"self-test: BETE reimbursement change with no change in law      = ${sb:,.0f}"
          f"  (passes if under $5,000)\n")

    paths.SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Solved so net State cost = ${TARGET / 1e6:.0f}m")
    print(f"  {'':4} {'rate':>5} {'exemption':>10} {'gross':>8} "
          f"{'BETE':>8} {'displaced':>10} {'net':>7} {'mill':>9}")
    solved = []
    for sid, label, E_canon, rate in R.he_canonical():
        E = solve(m, mvr, xw, rate)
        net, gross, bete, disp = net_cost(m, mvr, xw, E, rate)
        s = he_model(mvr, E, rate)
        # The statewide mill change, on the one measure the model reports.
        mp = T.levy_weighted(pd.Series((s["mill_delta"] / (s["mill"] - s["mill_delta"])).to_numpy(),
                                       index=T._key(s["Place"]).to_numpy()))
        print(f"  {sid:4} {100*rate:4.0f}% ${int(E):>9,} "
              f"{gross/1e6:7.1f}M {bete/1e6:+7.2f}M {disp/1e6:+9.1f}M "
              f"{net/1e6:6.2f}M {100*mp:+8.3f}%")
        solved.append((sid, label, E_canon, E, rate, mp, gross, bete, s))

    # New data moves the solved exemptions. They are recorded, not re-solved on
    # every run, so stop and print the replacement entries to paste in.
    if any(abs(E - E_canon) >= 0.5 for _, _, E_canon, E, *_ in solved):
        he, files = [], []
        for sid, label, _, E, rate, mp, gross, bete, _ in solved:
            new = f"{sid} HE ${int(E):,} @ {round(100 * rate)}%"
            he.append(f'    "{new}": ({int(E - CURRENT_EXEMPTION):_}, {mp:+.5f}, '
                      f'{gross:_.1f}, {bete:_.1f}),')
            files.append(f'    "{new}": "{T.HE_SCENARIO_FILES[label]}",')
        raise SystemExit(
            "\nThe solved exemptions differ from those recorded. Replace the entries of\n"
            "HE_SCENARIOS in model/ptfc_recalibrate.py with\n\n" + "\n".join(he) +
            "\n\nand of HE_SCENARIO_FILES in model/ptfc_takeup.py with\n\n" + "\n".join(files) +
            "\n\nthen run this step again.")
    for sid, label, *_, s in solved:
        fname = T.HE_SCENARIO_FILES[label]
        s.to_csv(paths.SCENARIO_DIR / fname, index=False)
        print(f"  {sid}  wrote {fname}")
