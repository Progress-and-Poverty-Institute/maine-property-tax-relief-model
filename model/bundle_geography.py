#!/usr/bin/env python3
"""Geography for the dashboard: household impacts by PUMA, mill changes by town.

The two geographies are kept separate on purpose.

  PUMA   Every household figure is modelled at PUMA level, because PUMS places
         a household in one of ten survey areas and no finer. Relief, gains,
         burdens and household counts are reported here and nowhere else.

  TOWN   The municipal model solves all 494 towns individually, so a town's
         mill rate change is known exactly. Nothing else about a town is. The
         town rows serve the archetype vignettes, which are set in a real town,
         and the Task Force's question about service centres.

Mixing them would imply town-level household precision the model does not have.

Units. The homestead exemption files (scenarios 1-3 and 15-19) carry `mill` and
`mill_delta` as rates, so the proportional change is
`mill_delta / (mill - mill_delta)`. The reallocation and Homestead Plus files
(scenarios 9-14) carry `dmillpct` in percent. Everything leaves here as a
fraction, so 0.0635 means a 6.35% rise in that town's mill rate.

Statewide figures. `mill_summary` turns the town changes into the one statewide
measure the dashboard, the Explorer and the report all quote: the levy-weighted
mean of the towns' proportional changes, shown in mills against the average
full-value rate on homesteads.

Coverage. The homestead files carry 494 towns and the reallocation files 481.
A town missing from a scenario is emitted as null rather than zero, because
"not modelled" and "no change" are different facts and a chart must not draw
them the same way. The scenario files are written by earlier pipeline steps.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ptfc_takeup as T
import reallocation as RA
import local_scenarios as LS

import paths

SCEN_DIR = paths.SCENARIO_DIR
CLASS_PATH = paths.MUNI_CLASSIFICATION

# Scenarios that move a mill rate. Scenarios 4-8 change the credit only, so a
# town's rate is untouched under them.
MILL_SCENARIOS = ["1", "2", "3", "9", "10", "11", "12", "13", "14",
                  "15", "16", "17", "18", "19"] + LS.mill_ids()
HP_FILE = "s14_homestead_plus.csv"

SERVICE_LABEL = {
    "Primary": "Primary service centre",
    "Secondary": "Secondary service centre",
    "Specialized": "Specialized service centre",
    "Small": "Small service centre",
    "SC-adjacent": "Service centre adjacent",
    "Non-SC": "Not a service centre",
    "UT": "Unorganised territory",
}


def _wmean(v, w):
    s = float(w.sum())
    return float((v * w).sum() / s) if s else float("nan")


def puma_rows(scen: dict, m) -> list:
    """One row per scenario per PUMA, rural to urban."""
    d = m.df
    W = m.W.astype(float)
    puma = d["PUMA"].to_numpy()
    # Divide by max(income, 1) over positive incomes only, matching
    # archetypes.net_burden.
    raw_inc = d["income"].to_numpy().astype(float)
    pos = raw_inc > 0
    inc = np.maximum(raw_inc, 1.0)
    tax0 = d["prop_tax"].to_numpy().astype(float)
    rows = []
    for sid, sc in scen.items():
        total = sc.delivered
        for i, q in enumerate(T.PUMA_ORDER):
            k = puma == q
            hh = float(W[k].sum())
            dol = float((sc.vec * W)[k].sum())
            d_bill = (sc.bills - tax0) if sc.bills is not None else np.zeros_like(tax0)
            rows.append(dict(
                s=sid, puma=int(q), label=T.PUMA_LABEL[q], rank=i + 1,
                households=hh,
                delivered=dol,
                share_of_delivered=(dol / total) if total else 0.0,
                per_hh=dol / hh if hh else 0.0,
                net_pct_income=_wmean(sc.vec[k & pos] / inc[k & pos], W[k & pos]),
                bill_pct_income=_wmean(d_bill[k & pos] / inc[k & pos], W[k & pos]),
                # Ratio of totals: the area's net gain over the area's income.
                # `net_pct_income` above is a mean of household ratios and is
                # dominated by households with a few hundred dollars of income.
                gain_pct_income=float((sc.vec * W)[k & pos].sum()
                                      / (raw_inc * W)[k & pos].sum()),
                better=sc.better(k, W), worse=sc.worse(k, W)))
    return rows


def _he_pct(fname: str) -> pd.Series:
    s = pd.read_csv(SCEN_DIR / fname)
    m0 = s["mill"] - s["mill_delta"]
    return pd.Series((s["mill_delta"] / m0).to_numpy(),
                     index=T._key(s["Place"]).to_numpy())


def _realloc_pct(fname: str) -> pd.Series:
    s = pd.read_csv(SCEN_DIR / fname)
    return pd.Series((s["dmillpct"] / 100.0).to_numpy(),
                     index=T._key(s["Place"]).to_numpy())


def _town_pct() -> dict:
    """Scenario id -> each town's proportional mill change, indexed by town key."""
    pct = {}
    for sid, label in zip(["1", "2", "3"], list(T.HE_SCENARIO_FILES)):
        pct[sid] = _he_pct(T.HE_SCENARIO_FILES[label])
    for sid in ["9", "10", "11", "12", "13"]:
        pct[sid] = _realloc_pct(RA.SCENARIOS[sid][1])
    pct["14"] = _realloc_pct(HP_FILE)
    pct["15"] = _he_pct("s15_task_force.csv")      # written by task_force.Combo.write_towns
    pct["16"] = _he_pct("s16_task_force.csv")
    pct["17"] = _he_pct("s17_task_force.csv")
    pct["18"] = _he_pct("s18_task_force.csv")
    pct["19"] = _he_pct("s19_task_force.csv")
    for sid in LS.mill_ids():
        pct[sid] = _he_pct("s%s_local.csv" % sid)   # written by bundle_scenarios.load
    return pct


def mill_summary() -> dict:
    """The statewide mill rate today, and each scenario's average change in it.

    `average` is today's average full-value mill rate on homesteads: each town's
    nominal rate times its certified ratio, weighted by its homestead count (13.86
    mills in the 2024 MVR), the weighting the household model uses for each
    survey area's rate.

    `change[sid]` is the levy-weighted mean of the towns' proportional changes
    (ptfc_takeup.levy_weighted),

        sum(change_i * commitment_i) / sum(commitment_i)

    over the towns the scenario models, with today's commitment as the weight.
    It equals the proportional change in the statewide levy that the new rates
    would raise on today's bases. In mills it is `change * average`. Scenarios
    that change only the credit leave every rate as it is and are not listed.
    """
    mvr = T.load_mvr(T.MVR_YEAR)
    for c in ("hstead_count", "mill_fv"):
        mvr[c] = pd.to_numeric(mvr[c], errors="coerce")
    ok = mvr["mill_fv"].notna() & mvr["hstead_count"].notna()
    average = 1000.0 * float((mvr.loc[ok, "mill_fv"] * mvr.loc[ok, "hstead_count"]).sum()
                             / mvr.loc[ok, "hstead_count"].sum())
    change = {sid: T.levy_weighted(s) for sid, s in _town_pct().items()}
    return dict(average=average, change=change)


def town_rows() -> list:
    """One row per town: its classification, and its mill change per scenario."""
    pct = _town_pct()
    cl = pd.read_csv(CLASS_PATH)
    cl["key"] = T._key(cl["MUNI"])
    cl = cl.drop_duplicates("key").set_index("key")

    keys = sorted(set().union(*[set(v.index) for v in pct.values()]))
    rows = []
    for k in keys:
        c = cl.loc[k] if k in cl.index else None
        row = dict(
            town=k,
            service=(SERVICE_LABEL.get(str(c["MuniType_Service"]))
                     if c is not None else None),
            size=(str(c["MuniType_Size"]) if c is not None else None),
            economy=(str(c["MuniType_Economy"]) if c is not None else None))
        for sid in MILL_SCENARIOS:
            v = pct[sid].get(k)
            row["s" + sid] = (None if v is None or not np.isfinite(v)
                              else round(float(v), 6))
        rows.append(row)
    return rows

