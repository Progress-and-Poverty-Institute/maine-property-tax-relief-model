#!/usr/bin/env python3
"""Pick a real Maine town and a real household for each archetype's vignette.

A vignette is where a reader meets one household rather than a distribution, so
it is set in a named town with that town's actual mill rate and its actual mill
rate change under each scenario. The municipal model solves all 494 towns, so
those town-level figures are exact even though no household in the model lives
in a named town.

The archetype is modelled at PUMA level and the vignette at town level, so the
two do not reconcile exactly: a vignette's bill is a worked example of a
household like this one in this town, not a measurement of the archetype.
`mill_gap` is reported so the size of that difference is visible.

Town selection. Candidates are towns in the archetype's home PUMA (see
`home_pumas`). Each is scored on how close the town's full value mill is to the
mill that reproduces the archetype's median bill (see `_target_mill`), with the
refinements below.

A second criterion was designed but never took effect in the published build:
that the town's mill change across the scenarios should be close to its PUMA's
average. The PUMA averages it compared against were all undefined (renters
have no bill to divide by), so the criterion added the same amount to every
candidate. It was removed on 25 November 2026 so the code does what the
published vignettes were chosen by. Restored correctly (owners with a bill
only), it would move 8 of the 13 vignettes to other towns, and the written
vignettes are about the households in these towns.

Town median income and home value are not scoring criteria. The narrow
archetypes are atypical by construction (a burdened household has a low income
against its bill), so matching town medians to them pulls every burdened
vignette towards the poorest available town and away from a good mill fit.
Town median home value is used only to break near-ties.

The bill is computed, not copied: (home value - exemption) times the town's full
value mill, so it is calibrated to the Municipal Valuation Return (MVR) like
every other figure here rather than taken from the household's reported tax. On
like-for-like terms (mean against mean, homestead properties only) PUMS owner
property taxes run about 3% below the MVR, so a vignette bill is close to what a
household of that type reports.

Every mill here is a full value rate: the nominal rate times the town's
certified ratio. Maine towns assess at a declared fraction of market value, so a
town assessing at 80% with a nominal 8 mills has an effective 6.4 mills on
market value. The median certified ratio is 0.990 and the range 0.50 to 1.12.

Towns below MIN_POP are dropped, because a very small plantation is an
implausible setting and its rate is volatile. Service centres are then promoted
until at least MIN_SERVICE_CENTRES vignettes sit in one, because the Task Force
asks specifically about service centres and scenarios 9 and 10 affect them
most.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import archetypes as A
import bundle_geography as GEO
import ceiling_redesign as C
import ptfc_engine as E
import ptfc_takeup as T

import paths

XWALK = paths.XWALK_MUNI_PUMA
ACS_PATH = paths.MUNI_ACS

# The population floor keeps vignettes plausible and avoids towns with volatile
# rates. Maine has many functioning municipalities of 1,200 people, and a higher
# floor leaves too few candidates in the Aroostook and Washington area.
MIN_POP = 1_200
MIN_SERVICE_CENTRES = 4
MIN_PUMAS = 10           # every survey area: thirteen vignettes, ten areas
MIN_SHARE = 0.04         # minimum share of an archetype a home PUMA must hold
SERVICE_SET = {"Primary service centre", "Secondary service centre",
               "Small service centre", "Specialized service centre"}


def town_frame() -> pd.DataFrame:
    """Every town with its PUMA, population, full-value mill and mill changes."""
    mvr = T.load_mvr(T.MVR_YEAR)
    tf = pd.DataFrame({
        "key": T._key(mvr["Place"]),
        "mill_fv": (pd.to_numeric(mvr["mill_rate"], errors="coerce")
                    * pd.to_numeric(mvr["certified_ratio"], errors="coerce")),
    }).groupby("key", as_index=False).mean()

    x = pd.read_csv(XWALK)
    x["key"] = T._key(x["MUNI"])
    x = (x.groupby("key", as_index=False)
           .agg(puma=("PUMACE20", "first"), pop=("pop2020", "sum"),
                town=("TOWN", "first"), county=("COUNTY", "first")))

    g = pd.DataFrame(GEO.town_rows()).rename(columns={"town": "key"})

    a = pd.read_csv(ACS_PATH)
    a["key"] = T._key(a["MUNI"])
    for src, dst in (("median_home_value_display", "town_home_value"),
                     ("median_hh_income_display", "town_income")):
        a[dst] = pd.to_numeric(
            a[src].astype(str).str.replace(r"[^0-9.]", "", regex=True),
            errors="coerce")
    a = a[["key", "town_home_value", "town_income"]].drop_duplicates("key")

    f = (tf.merge(x, on="key", how="inner")
           .merge(g, on="key", how="left")
           .merge(a, on="key", how="left"))
    return f.dropna(subset=["mill_fv", "puma"])


def home_pumas(masks: dict, m) -> dict:
    """archetype -> PUMA, spread across the state.

    Placing each vignette where its household type is most numerous would put
    all thirteen in southern Maine, because southern PUMAs hold the most
    households of every type. That would hide the main geographic result: the
    reallocation scenarios move money from the north and east to the southern
    coast.

    So each archetype goes where it is over-represented rather than merely
    numerous, measured as lift: its share of that PUMA's households against its
    share of Maine's. A PUMA qualifies only if it holds at least MIN_SHARE of
    the archetype, so no vignette is set where the type is rare. Assignment is
    greedy, most-constrained archetype first, taking the highest-lift PUMA not
    yet used until MIN_PUMAS are covered. MIN_PUMAS is all ten, since with
    thirteen archetypes and ten areas any lower floor can leave whole regions
    without a vignette.
    """
    W = m.W.astype(float)
    puma = m.df["PUMA"].to_numpy()
    tot = W.sum()
    cand = {}
    for aid, mk in masks.items():
        mk = np.asarray(mk)
        w = W[mk]
        base = w.sum() / tot
        rows = []
        for q in T.PUMA_ORDER:
            inq = puma == q
            n = float(W[mk & inq].sum())
            if n / w.sum() < MIN_SHARE:
                continue
            lift = (n / float(W[inq].sum())) / base if base else 0.0
            rows.append((lift, n, q))
        rows.sort(reverse=True)
        cand[aid] = rows or [(1.0, float(w.sum()), int(
            pd.Series(w).groupby(pd.Series(puma[mk])).sum().idxmax()))]

    order = sorted(cand, key=lambda a: len(cand[a]))
    used, out = set(), {}
    for aid in order:
        fresh = [r for r in cand[aid] if r[2] not in used]
        pick_from = fresh if (fresh and len(used) < MIN_PUMAS) else cand[aid]
        out[aid] = int(pick_from[0][2])
        used.add(out[aid])
    return out


def _target_mill(mask, in_home, m, W, hv) -> float:
    """Full value mill a town must levy to reproduce this archetype's bill.

    `median tax / (median home value - exemption)` over the archetype's owners
    statewide, because the archetype figures a reader compares the vignette
    against are statewide. A vignette's bill is (home value - exemption) times
    the town's rate, so this is the rate at which the vignette reproduces the
    archetype's median bill; the average rate the archetype's households face
    does not, because its median tax, median value and average rate come from
    different households.

    Renter archetypes have no home value to divide by. Their counted tax is 15%
    of rent and no mill rate enters it, so they fall back to the
    weighted-average rate the archetype faces in its home PUMA.
    """
    import ptfc_recalibrate as _R
    tax = pd.to_numeric(m.df["prop_tax"], errors="coerce").to_numpy()
    own = np.asarray(m.owner)
    k = np.asarray(mask) & own & np.isfinite(hv) & np.isfinite(tax) & (hv > _R.CURRENT_EXEMPTION)
    if k.sum() >= 30:
        mv = A._wmedian(hv[k], W[k])
        mt = A._wmedian(tax[k], W[k])
        if np.isfinite(mv) and np.isfinite(mt) and mv > _R.CURRENT_EXEMPTION and mt > 0:
            return float(mt / (mv - _R.CURRENT_EXEMPTION))
    return float(np.average(m.mill_h[in_home], weights=W[in_home]))


def pick(scen: dict, m, overrides: dict | None = None) -> pd.DataFrame:
    """One town per archetype. `overrides` maps archetype id -> town key."""
    d, W = m.df, m.W.astype(float)
    hv = pd.to_numeric(d["home_value"], errors="coerce").to_numpy()
    inc = d["income"].to_numpy().astype(float)
    masks = dict(A.broad(d))
    masks.update(A.narrow_rules(d, m.base)[0])

    towns = town_frame()

    puma = d["PUMA"].to_numpy()
    homes = home_pumas(masks, m)
    own_burden = A.net_burden(d, m.base)
    rows = []
    for aid, mk in masks.items():
        mk = np.asarray(mk)
        w = W[mk]
        home_puma = homes[aid]
        in_home = mk & (puma == home_puma)
        target_mill = _target_mill(mk, in_home, m, W, hv)

        cand = towns[(towns["puma"] == home_puma) & (towns["pop"] >= MIN_POP)].copy()
        if cand.empty:
            cand = towns[towns["puma"] == home_puma].copy()
        cand["mill_gap"] = (cand["mill_fv"] - target_mill).abs()
        own = np.asarray(m.owner)
        hv_ok = in_home & own & np.isfinite(hv)
        tgt_hv = (A._wmedian(hv[hv_ok], W[hv_ok]) if hv_ok.any() else np.nan)
        tgt_inc = A._wmedian(inc[in_home], W[in_home])
        r = cand["mill_gap"].max() - cand["mill_gap"].min()
        cand["score"] = 0.0 if r == 0 else (cand["mill_gap"] - cand["mill_gap"].min()) / r
        # Plausibility breaks ties; it does not choose. Among towns within 10%
        # of the score range of the best, prefer the one whose median home value
        # is closest to the archetype's in log terms, so a high-value archetype
        # is not set in a low-value town when an equally good mill fit exists.
        if np.isfinite(tgt_hv) and tgt_hv > 0:
            rng = float(cand["score"].max() - cand["score"].min())
            band = cand["score"].min() + 0.10 * (rng if rng > 0 else 1.0)
            ratio = pd.to_numeric(cand["town_home_value"],
                                  errors="coerce") / tgt_hv
            cand["tie"] = np.abs(np.log(ratio.where(ratio > 0)))
            cand["tie"] = cand["tie"].fillna(cand["tie"].max())
            cand["tie"] = np.where(cand["score"] <= band, cand["tie"],
                                   cand["tie"].max() + 1.0)
        else:
            cand["tie"] = 0.0
        cand = cand.sort_values(["tie", "score"])

        # Second pass. The household is chosen after the town and absorbs
        # whatever the town's rate leaves over, and it must also match the
        # archetype's age and household size. So for each of the leading
        # BURDEN_FIT_K candidates, the household that would be chosen is chosen,
        # the burden it would show is computed, and towns landing near the
        # archetype's own median burden are preferred. This adjusts the score;
        # a town still has to be a reasonable mill fit to be in the running.
        fam = "broad" if aid.startswith("B") else "narrow"
        bk = np.asarray(mk) & np.isfinite(own_burden)
        med_burden = (float(A._wmedian(own_burden[bk], W[bk]))
                      if bk.any() else np.nan)
        if np.isfinite(med_burden) and med_burden > 0:
            head = cand.head(BURDEN_FIT_K)
            err = {}
            for ix, t in head.iterrows():
                mill_t = float(t["mill_fv"])
                j = representative(np.asarray(mk), m,
                                   town_mill=mill_t, family=fam,
                                   archetype=aid.split()[0])
                vb = _vignette_burden(m, mill_t)[j]
                err[ix] = (abs(np.log(vb / med_burden))
                           if np.isfinite(vb) and vb > 0 else np.nan)
            ev = pd.Series(err, dtype=float)
            if ev.notna().any():
                ev = ev.fillna(ev.max())
                r = float(ev.max() - ev.min())
                zb = (ev - ev.min()) / r if r > 0 else ev * 0.0
                cand["burden_fit"] = np.nan
                cand.loc[zb.index, "burden_fit"] = zb.to_numpy()
                # Towns outside the tried set keep their place behind it.
                cand["burden_fit"] = cand["burden_fit"].fillna(1.0)
                cand["score"] = cand["score"] + BURDEN_FIT_W * cand["burden_fit"]
                cand = cand.sort_values(["tie", "score"])

        rows.append(dict(
            archetype=aid, family=("broad" if aid.startswith("B") else "narrow"),
            puma=home_puma, puma_label=T.PUMA_LABEL[home_puma],
            households=float(w.sum()), target_mill=target_mill,
            target_home_value=tgt_hv, target_income=tgt_inc,
            _cand=cand))

    out = pd.DataFrame(rows)

    # No town is used twice; the second-best town is usually a negligible
    # distance behind on score. Assigned greedily: the archetype whose best and
    # second-best candidates differ most has the most to lose from being
    # displaced, so it chooses first.
    regret = []
    for i, (_, r) in enumerate(out.iterrows()):
        c = r["_cand"]
        gap = (float(c.iloc[1]["score"] - c.iloc[0]["score"])
               if len(c) > 1 else np.inf)
        regret.append((-gap, i))
    taken, chosen = set(), [None] * len(out)
    for _, i in sorted(regret):
        c = out.iloc[i]["_cand"]
        free = c[~c["key"].isin(taken)]
        row = (free.iloc[0] if len(free) else c.iloc[0])
        taken.add(row["key"])
        chosen[i] = row

    # Promote service centres until the floor is met, taking the cheapest
    # swaps first: the archetype whose best service centre costs least score.
    def is_sc(row):
        return str(row.get("service")) in SERVICE_SET
    have = sum(is_sc(c) for c in chosen)
    if have < MIN_SERVICE_CENTRES:
        costs = []
        for i, (_, r) in enumerate(out.iterrows()):
            if is_sc(chosen[i]):
                continue
            sc_rows = r["_cand"][r["_cand"]["service"].isin(SERVICE_SET)]
            if sc_rows.empty:
                continue
            costs.append((float(sc_rows.iloc[0]["score"] - chosen[i]["score"]),
                          i, sc_rows.iloc[0]))
        for _, i, row in sorted(costs)[:MIN_SERVICE_CENTRES - have]:
            chosen[i] = row

    out["_mask"] = [np.asarray(masks[a]) for a in out["archetype"]]
    out = out.drop(columns=["_cand"])
    out["town"] = [c["town"] for c in chosen]
    out["key"] = [c["key"] for c in chosen]
    out["county"] = [c["county"] for c in chosen]
    out["service"] = [c["service"] for c in chosen]
    out["pop"] = [int(c["pop"]) for c in chosen]
    out["town_mill"] = [float(c["mill_fv"]) for c in chosen]
    out["town_home_value"] = [float(c["town_home_value"]) for c in chosen]
    out["town_income"] = [float(c["town_income"]) for c in chosen]
    out["mill_gap"] = out["town_mill"] - out["target_mill"]
    for sid in GEO.MILL_SCENARIOS:
        out["s" + sid] = [c.get("s" + sid) for c in chosen]

    # Hand-set towns from `overrides`, applied last and flagged in the frame
    # so the vignette records that its town was chosen rather than scored.
    if overrides:
        towns = towns.set_index("key")
        out["overridden"] = False
        for aid in list(out["archetype"]):
            short = aid.split()[0]
            key = overrides.get(short) or overrides.get(aid)
            if key is None:
                continue
            key = T._key(pd.Series([key])).iloc[0]
            if key not in towns.index:
                raise KeyError("override town not found: %s" % key)
            c = towns.loc[key]
            i = out.index[out["archetype"] == aid][0]
            out.loc[i, "town"] = c["town"]
            out.loc[i, "key"] = key
            out.loc[i, "county"] = c["county"]
            out.loc[i, "service"] = c["service"]
            out.loc[i, "pop"] = int(c["pop"])
            out.loc[i, "puma"] = int(c["puma"])
            out.loc[i, "puma_label"] = T.PUMA_LABEL[int(c["puma"])]
            out.loc[i, "town_mill"] = float(c["mill_fv"])
            out.loc[i, "town_home_value"] = float(c["town_home_value"])
            out.loc[i, "town_income"] = float(c["town_income"])
            out.loc[i, "overridden"] = True
            for sid in GEO.MILL_SCENARIOS:
                out.loc[i, "s" + sid] = c.get("s" + sid)
        out["mill_gap"] = out["town_mill"] - out["target_mill"]
    else:
        out["overridden"] = False
    return out


# Archetype id -> town, for a town set by hand rather than by scoring. Empty:
# every vignette town is scored.
OVERRIDES: dict[str, str] = {}


# --------------------------------------------------------------- households
# Vignette households chosen by hand, keyed on the PUMS household identifier
# (SERIALNO) so a pin survives a rebuilt extract. A vignette carries a
# narrative, and one that contradicts the finding it illustrates is worse than
# one slightly off a median. Each pin must match exactly one member of its
# archetype.
HOUSEHOLD_OVERRIDES = {
    # B6, renters aged 65 and over. The credit cuts the number of these
    # households paying above 6% of income by about 95%, the largest movement
    # in the set. B6 is 47.5% eligible and its median household falls just
    # outside eligibility, so scoring on medians picks a household receiving no
    # credit. This household is 75 (the archetype's median age), on $28,840
    # against a median of $27,564, and the credit takes it to 4.0% of income.
    "B6": "2020HU0222019",
    # N4, working-age owners living with a partner, 63% of whom receive the
    # credit. Scoring picks two unmarried adults sharing a house: the model
    # carries one tax return per household and so counts both incomes against
    # one filer's benefit base, where Maine would see two returns. That is a
    # model limitation, not a property of Maine policy. This household is a
    # married couple of 63, on $69,266 against an archetype median of $67,166,
    # in a $428,737 home against $437,486, receiving $529 and left at 8.7% of
    # income against the archetype's 8.0%.
    #
    # The archetype splits on the householder's age, while the credit asks
    # whether the householder or spouse is 65, so 10% of this working-age
    # archetype draws the senior benefit base and cap. This household is in the
    # 90% that does not, which is representative on the dimension that decides
    # the credit.
    "N4": "2022HU0075565",
    # N7, burdened renters. 63% of this archetype reports rent above income and
    # its median member sits at 111.5%, so scoring picks a household whose rent
    # exceeds its income, which reads as an error. The cause is the
    # denominator: among Maine renters reporting rent above income the median
    # rent ($12,791) is close to the all-renter median ($11,817) while the
    # median income is $7,346. The archetype selects on counted tax (15% of
    # rent) over income, so it concentrates these cases: 4.4% of renters
    # holding 41.5% of all rent-above-income cases in Maine.
    #
    # No cut corrects this. The ratio runs continuously from 52% at the tenth
    # percentile to 448% at the ninetieth, so any threshold slices through one
    # population rather than separating two, and an income floor of $7,500
    # still leaves 51.6% of the rest above 100%. Nothing in statute says a
    # reported income is wrong.
    #
    # So the archetype stands and the vignette uses one of the 37% of members
    # reporting rent below income: 46, living alone, in PUMA 1000, on $25,662
    # against $20,404 of rent, with survey weight 95. Its net burden is 6.08%
    # against the archetype's 8.60% median, because that median is driven by
    # the ratios this pin avoids; the two should be labelled wherever they
    # appear together.
    "N7": "2020HU0746791",
}

# How many of the best-scoring towns get the household-level burden check in
# `pick`, and how much the resulting burden fit counts against the mill fits.
# Larger values (K=40, W=6.0) choose the same towns.
BURDEN_FIT_K = 15
BURDEN_FIT_W = 1.5

# What a vignette household is matched on, and how hard, by archetype family.
# Broad archetypes are read for typicality ("this is what a Maine family with
# children looks like"), so age and household size matter as much as money.
# Narrow archetypes are atypical by construction and are read as what happens to
# one household, so the burden the vignette shows has to be right and
# composition only has to be believable.
WEIGHTS = {
    "broad":  dict(income=1.0, value=1.0, age=1.0, size=1.0, burden=0.5),
    "narrow": dict(income=1.0, value=1.0, age=0.5, size=0.5, burden=2.5),
}


_VB_CACHE: dict = {}


def _vignette_burden(m, mill):
    """Net burden every household would show if it were the vignette in this town.

    Used instead of the household's own reported tax-to-income ratio, because
    the dashboard recomputes a vignette's bill as (home value - exemption) times
    the town's full value mill. Results are cached per model and mill.
    """
    import ptfc_recalibrate as _R
    ex = _R.CURRENT_EXEMPTION
    ck = (id(m), round(float(mill), 9), round(float(ex), 4))
    if ck in _VB_CACHE:
        return _VB_CACHE[ck]
    d = m.df
    hv = pd.to_numeric(d["home_value"], errors="coerce").to_numpy()
    own = np.asarray(m.owner)
    bill = np.where(own & np.isfinite(hv), np.maximum(hv - ex, 0.0) * mill, 0.0)
    d2 = d.copy()
    d2["prop_tax"] = bill
    credit = np.asarray(E.credit(d2, m.p0), float)
    counted = np.where(own, bill, m.p0.rate_rent * A.CC.rent_for_credit(d))
    inc = d["income"].to_numpy().astype(float)
    out = np.where(inc > 0, (counted - credit) / np.maximum(inc, 1.0), np.nan)
    _VB_CACHE[ck] = out
    return out


def representative(mask, m, town_mill, family, archetype) -> int:
    """Index of the PUMS household that best stands for the archetype.

    A real row, not a synthetic average, so household composition, rent and
    senior status are internally consistent. Chosen as the member of the
    archetype closest to the archetype's weighted medians on a set of
    standardised criteria, weighted by family per WEIGHTS above.

    Medians and candidates are statewide, because the archetype figures a
    reader sets the vignette against are statewide. The town, drawn from the
    archetype's home PUMA, is what places the vignette. A household pinned in
    HOUSEHOLD_OVERRIDES is returned directly.
    """
    d, W = m.df, m.W.astype(float)
    full = np.asarray(mask)
    pin = HOUSEHOLD_OVERRIDES.get(archetype)
    if pin is not None:
        hit = np.flatnonzero(full & (d["SERIALNO"].to_numpy() == pin))
        if len(hit) != 1:
            raise KeyError(
                "household override %s for %s matches %d rows of that archetype; "
                "it must match exactly one" % (pin, archetype, len(hit)))
        return int(hit[0])
    inc = d["income"].to_numpy().astype(float)
    hv = pd.to_numeric(d["home_value"], errors="coerce").to_numpy()
    rent = pd.to_numeric(d["rent_annual"], errors="coerce").to_numpy()
    own = np.asarray(m.owner)
    owner_group = own[full].mean() > 0.5
    # The second matching dimension is the one that drives the household's
    # bill: home value for owners, rent for renters, because 15% of rent is a
    # renter's counted property tax.
    second = hv if owner_group else rent
    k = full
    if owner_group:
        k = k & own & np.isfinite(hv)
    k = k & np.isfinite(second)
    if not k.any():
        k = full & np.isfinite(second)
    if not k.any():
        k = full
    idx = np.flatnonzero(k)

    w = WEIGHTS[family]
    terms = [("income", inc), ("value", second),
             ("age", d["age_head"].to_numpy().astype(float)),
             ("size", d["NP"].to_numpy().astype(float)),
             ("burden", _vignette_burden(m, float(town_mill)))]

    # The burden term deliberately compares two different quantities: each
    # candidate's value is the burden it would show as the vignette in this
    # town, and the target is the archetype's own median burden at each
    # household's actual rate, which is the figure a reader compares the
    # vignette against.
    own_burden = A.net_burden(d, m.base)
    z = np.zeros(len(idx))
    for name, v in terms:
        ok = np.isfinite(v[k])
        if not ok.any():
            continue
        tv = own_burden if name == "burden" else v
        tok = np.isfinite(tv[k])
        if not tok.any():
            continue
        t = A._wmedian(tv[k][tok], W[k][tok])
        sd = np.nanstd(v[idx]) or 1.0
        z = z + w[name] * np.nan_to_num(((v[idx] - t) / sd) ** 2, nan=0.0)
    return int(idx[int(np.argmin(z))])


def _burden(counted, credit, income):
    """Counted tax net of credit, as a share of income.

    Matches `archetypes.net_burden`: divide by max(income, 1) and leave it
    undefined at or below zero income.
    """
    if not np.isfinite(income) or income <= 0:
        return float("nan")
    return float((counted - credit) / max(income, 1.0))


def _credit_one(sc, m, rd, i, bill, counted=None):
    """This household's total statutory credit under `sc`, at a given bill.

    Every branch calls the same engine as the scenario totals; nothing here
    reimplements a credit rule. The ceiling designs are evaluated by swapping
    this one row's values into the Redesign's own vectors and reading the
    answer back, so they cannot drift from the published scenario.

    A ceiling design pays the greater of its guarantee and the household's
    current-law credit, so both sides are evaluated at the vignette's bill.
    The ceiling is measured against counted tax (`counted`): the owner's bill,
    or 15% of the renter's rent. Renters arrive with bill = 0, which is right
    for E.credit, since it adds the rent proxy itself.
    """
    row = m.df.iloc[[i]]
    tax = np.array([bill], float)
    base = float(E.credit(row, m.p0, tax)[0])
    if sc is None:
        return base
    if sc.hplus:
        return float(E.homestead_plus(row, sc.params, prop_tax=tax)[0])
    if isinstance(sc.params, C.Design):
        keep_t, keep_b = rd.T[i], rd.base[i]
        try:
            rd.T[i] = counted
            rd.base[i] = base
            return float(rd.credit(sc.params)[i])
        finally:
            rd.T[i], rd.base[i] = keep_t, keep_b
    if getattr(sc.params, "two_tier", False):   # S19's two-tier credit (task_force)
        import task_force as CB
        return float(CB.credit(row, sc.params, tax, m.p0)[0])
    return float(E.credit(row, sc.params, tax)[0])


def relief(picks: pd.DataFrame, scen: dict, m) -> list:
    """One worked example per archetype per scenario, 182 in all.

    The bill is computed at the town's full value mill, not copied from PUMS
    (see the module docstring).

    Take-up is 100%: a vignette is one household, and a fraction of a credit
    describes nobody. Every other figure on the dashboard is take-up weighted,
    so the two should be labelled wherever they appear together.
    """
    d = m.df
    hv = pd.to_numeric(d["home_value"], errors="coerce").to_numpy()
    inc = d["income"].to_numpy().astype(float)
    own = np.asarray(m.owner)
    rent = pd.to_numeric(d["rent_annual"], errors="coerce").to_numpy()
    # Two rents on purpose: `rent` is the fee the household pays and is what the
    # vignette reports; `rentc` is the occupancy portion the statute counts.
    # They differ only for congregate care; see congregate_care.py.
    rentc = A.CC.rent_for_credit(d)
    rent_share = float(m.p0.rate_rent)
    rd = C.Redesign(m)
    # Redesign.base aliases the Model's own current-law credit vector, and
    # _credit_one swaps one element of it per vignette. Copy first, so a
    # worked example can never write through to the scenario results.
    rd.base = np.array(rd.base, dtype=float, copy=True)
    rows = []
    for _, p in picks.iterrows():
        mill = float(p["town_mill"])
        i = representative(p["_mask"], m,
                           town_mill=mill, family=p["family"],
                           archetype=p["archetype"].split()[0])
        is_owner = bool(own[i])
        value = float(hv[i]) if np.isfinite(hv[i]) else 0.0
        bill0 = max(value - 25_000.0, 0.0) * mill if is_owner else 0.0
        cred0 = _credit_one(None, m, rd, i, bill0)
        for sid, sc in scen.items():
            dp = p.get("s" + sid)
            dp = 0.0 if dp is None or not np.isfinite(dp) else float(dp)
            if is_owner:
                bill = max(value - sc.exemption, 0.0) * mill * (1.0 + dp)
            else:
                bill = 0.0
            # Counted tax is what the statute measures a household against and
            # the only quantity comparable between an owner and a renter: the
            # owner's bill, or 15% of the renter's rent, which 36 M.R.S.
            # 5219-KK deems to be property tax. The ceiling designs measure it
            # too, so it is computed before the credit.
            ct0 = bill0 if is_owner else rent_share * rentc[i]
            ct = bill if is_owner else rent_share * rentc[i]
            cred = _credit_one(sc, m, rd, i, bill, counted=ct)
            rows.append(dict(
                a=p["archetype"].split()[0], s=sid, town=p["town"],
                owner=is_owner, income=float(inc[i]), home_value=value,
                rent_annual=float(rent[i]) if np.isfinite(rent[i]) else 0.0,
                town_mill=mill, town_dmill=dp,
                bill_base=bill0, bill_scen=bill,
                counted_tax_base=float(ct0), counted_tax_scen=float(ct),
                credit_base=cred0, credit_scen=cred,
                net=(cred - cred0) - (bill - bill0),
                burden_base=_burden(ct0, cred0, inc[i]),
                burden_scen=_burden(ct, cred, inc[i])))
    return rows
