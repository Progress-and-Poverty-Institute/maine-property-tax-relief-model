#!/usr/bin/env python3
"""Build the data file behind the dashboard: output/dashboard.json.

Every figure the dashboard shows is computed here from the model: scenario
costs and totals, results by archetype, income decile and PUMA, burden
histograms, municipal mill-rate changes and worked household examples. The run
ends with reconciliation checks, for example that the archetype cells add up to
each scenario's delivered total.

The two archetype families use different conventions because they answer
different questions:

  BROAD  tile all of Maine and are read for distributional effect, so their
         cells are delivered dollars, credit x take-up. Summed over 100,000+
         households, the expectation is the meaningful quantity, and the
         columns reconcile to the per-scenario delivered totals.

  NARROW tile the burdened group and are read as what happens to one
         household, so their cells use the full statutory credit. A household
         either claims or does not; receiving a fraction of a credit
         describes nobody.

Archetype membership is fixed on current law in both families, so composition
never shifts between scenarios.

For the homestead scenarios the household-level view is the enrolled
homesteader, not the coverage-blended expectation. Blending is right for sums
and wrong for a representative household, which either holds a homestead or
does not (see ptfc_recalibrate.Model._he_legs).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import paths                      # noqa: E402

import archetypes as A            # noqa: E402
import bundle_geography as GEO    # noqa: E402
import bundle_scenarios as B      # noqa: E402
import commercial_archetypes as CA  # noqa: E402
import bundle_vignettes as VIG    # noqa: E402
import ptfc_recalibrate as R      # noqa: E402
import baseline_programs as BP    # noqa: E402


def _rows(df):
    """A DataFrame as a list of JSON-ready records."""
    return json.loads(df.to_json(orient="records"))


BASIS = {"HE": "enrolled homesteader", "HPLUS": "enrolled homesteader"}

# ------------------------------------------------------------------ burden
# Bins for the dashboard's burden histograms and its 6% threshold chart.
# Burden is counted property
# tax as a share of household income: the owner's actual bill, or 15% of a
# renter's counted rent, which is what 36 M.R.S. 5219-KK deems to be property
# tax. Edges are the bin BOUNDARIES; there is one more label than edge.
BURDEN_EDGES = (0.02, 0.04, 0.06, 0.08, 0.10)
BURDEN_LABELS = ["under 2%", "2% to 4%", "4% to 6%",
                 "6% to 8%", "8% to 10%", "above 10%"]


def burden_bins(b, W, mask):
    """Weighted household counts per BURDEN_LABELS over `mask`.

    Households with income at or below zero are DROPPED, not binned at zero:
    the ratio is undefined for them. They are about 1.1% of Maine and 87% of
    them are PTFC-eligible, so they are excluded as unmeasurable rather than as
    comfortable. `burden_undefined` reports how many per archetype, so that no
    view can present these bins as covering the whole group.

    Bins are RIGHT-CLOSED: a household at exactly 4.00% counts as "2% to 4%",
    not "4% to 6%". This is not cosmetic. The Fairness Credit pays property tax
    above the income offset, so every claimant whose credit is not capped lands
    at EXACTLY the offset by construction. With left-closed bins that mass would
    sit just inside "4% to 6%" under current law and drop into "2% to 4%" the
    moment a scenario cuts the offset, making Scenario 11 read as a 19-point
    improvement for the older-owner archetype on an average gain of $38, and
    undercounting how many households today's programme already brings to the
    line (that archetype is 75.4% at or below 4%, not 60.3%).

    Right-closed binning also makes the 6% edge agree with the burdened-group
    rule in `archetypes.burdened`, which is strictly greater than 6.0%.
    """
    k = np.asarray(mask) & np.isfinite(b)
    # Round before binning. The uncapped claimants sit at the 4% offset only up
    # to floating-point noise, and the noise differs by platform, which can put
    # hundreds of households on opposite sides of the 4% edge. Nine decimals is
    # far below any real burden difference and far above double-precision error.
    idx = np.digitize(np.round(b[k], 9), BURDEN_EDGES, right=True)
    w = W[k]
    return [float(w[idx == i].sum()) for i in range(len(BURDEN_LABELS))]


def basis_for(note, base_is):
    """The convention label, which depends on the ARCHETYPE as well as the scenario.

    `BASIS` names the convention a homestead scenario is forced into. The survey
    never says who holds a homestead exemption, so the model carries two legs per
    owner and these rows report the ENROLLED leg rather than the coverage blend.

    A renter has no exemption leg at all. `Model.he_bill` gives a renter only the
    mill change, and that is zero because renters carry no property tax in the
    survey. So no choice of convention arises on a renter row, and the label is
    the ordinary one.

    The label governs the dollar and burden columns only. `share_better` and
    `share_worse` come from `Scen._share()` and are always leg-blended, because
    counting households whose exemption status is unobserved is only meaningful
    as an expectation. One row can therefore carry a coverage-blended count
    beside an enrolled-homesteader dollar figure.
    """
    return note if base_is == "owners" else "full statutory credit"


def scenario_world(sc, d):
    """(frame under the scenario, total statutory credit, basis note).

    Every scenario from `bundle_scenarios` carries its own household-level bill
    and credit vectors, so this drops them into a copy of the frame.
    """
    dd = d.copy()
    dd["prop_tax"] = sc.bills
    return dd, sc.credit, BASIS.get(sc.family, "full statutory credit")


def _json_safe(x):
    """NaN and infinity as null: JSON has no NaN, and a browser will not parse one."""
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x


def build():
    return _json_safe(_build())


def _build():
    m = R.Model()
    d = m.df.copy()
    W = d["WGTP"].to_numpy().astype(float)
    el = m.base > 0

    broad_masks = A.broad(d)
    narrow_masks = A.narrow_rules(d, m.base)[0]
    scen = B.load(m)                        # every scenario, one shape
    picks = VIG.pick(scen, m, VIG.OVERRIDES)
    vec = {k: s.vec for k, s in scen.items()}
    ALL = np.ones(len(d), bool)

    # ---- broad: delivered dollars ------------------------------------
    broad_cells = []
    for aid, mk in broad_masks.items():
        mk = np.asarray(mk)
        hh = float(W[mk].sum())
        for sid, sc in scen.items():
            v = sc.vec
            dol = float((v * W)[mk].sum())
            # Counts come from the scenario, never from testing `v`: scenarios
            # 1-3 and 14 blend two homestead legs and the blend cannot be
            # counted. See bundle_scenarios.Scen.
            broad_cells.append(dict(
                s=sid, a=aid.split()[0], households=hh, delivered=dol,
                per_hh=dol / hh if hh else 0.0,
                gaining=hh * sc.better(mk, W),
                losing=hh * sc.worse(mk, W)))

    # ---- income deciles ----------------------------------------------
    # Weighted deciles of household income across every Maine household.
    inc = d["income"].to_numpy()
    # Stable sort: incomes tie (top-coded and rounded survey values), and the
    # default quicksort orders ties differently by platform, which can move a
    # decile cut.
    o = np.argsort(inc, kind="stable")
    cw = np.cumsum(W[o]) / W.sum()
    dec = np.empty(len(d), int)
    dec[o] = np.clip((cw * 10).astype(int), 0, 9)
    dec += 1
    dec_cuts = [float(np.max(inc[dec == k])) for k in range(1, 11)]

    # ---- burden, three series ----------------------------------------
    # `before_relief` strips BOTH programmes and lets the mill rate respond to
    # the exemption coming off the base, which is why it comes from the
    # baseline engine rather than from arithmetic here. `now` is current law
    # and is archetypes.net_burden.
    # The per-scenario series is built in the scenario loop below.
    _bl = BP.Baseline(m)
    _w = _bl.worlds(dynamic=True, delivered=False)
    _rent = A.RENT_SHARE * A.CC.rent_for_credit(d)
    burden_before = np.where(inc > 0,
                             (_w["neither"].to_numpy() + _rent) / np.maximum(inc, 1.0),
                             np.nan)
    burden_now = A.net_burden(d, m.base)

    def _fam_masks():
        yield "broad", broad_masks
        yield "narrow", narrow_masks

    burden_rows, burden_undefined = [], []
    for fam, masks in _fam_masks():
        for aid, mk in masks.items():
            mk = np.asarray(mk)
            for name, bvec in (("before_relief", burden_before), ("now", burden_now)):
                burden_rows.append(dict(a=aid.split()[0], family=fam, series=name,
                                        bins=burden_bins(bvec, W, mk)))
            burden_undefined.append(dict(
                a=aid.split()[0], family=fam,
                households=float(W[mk & ~np.isfinite(burden_now)].sum())))
    for name, bvec in (("before_relief", burden_before), ("now", burden_now)):
        burden_rows.append(dict(a="ALL", family="all", series=name,
                                bins=burden_bins(bvec, W, ALL)))
    burden_undefined.append(dict(a="ALL", family="all",
                                 households=float(W[~np.isfinite(burden_now)].sum())))

    # ---- where each archetype lives ----------------------------------
    # Four-way typology from archetypes.REGIONS. The "ALL" row is the statewide
    # baseline, and no archetype share should ever be quoted without it.
    _reg = d["PUMA"].map(A.REGIONS).to_numpy()
    _areas = sorted(set(A.REGIONS.values()))
    archetype_areas = []
    for fam, masks in _fam_masks():
        for aid, mk in masks.items():
            mk = np.asarray(mk)
            base = W[mk].sum()
            for rg in _areas:
                archetype_areas.append(dict(
                    a=aid.split()[0], family=fam, area=rg,
                    share=float(W[mk & (_reg == rg)].sum() / base)))
    for rg in _areas:
        archetype_areas.append(dict(a="ALL", family="all", area=rg,
                                    share=float(W[_reg == rg].sum() / W.sum())))

    # `households` and `gain_pct_income` let the dashboard show each decile's
    # share of relief, dollars per household, and net gain as a share of income.
    #
    # `gain_pct_income` is a RATIO OF TOTALS: the decile's net gain over the
    # decile's income, households at or below zero income excluded. It is
    # deliberately NOT the mean of each household's own ratio, which is how
    # puma_rows builds `net_pct_income`. In the bottom decile a mean of ratios
    # is dominated by households with a few hundred dollars of income: under
    # Scenario 1 it reads 2.7% of income where the decile's $31 average gain
    # against its incomes is about 0.3%.
    pos = inc > 0

    def _dec_row(sid, aid, k, v, m2):
        hh = float(W[m2].sum())
        kp = m2 & pos
        inc_tot = float((inc[kp] * W[kp]).sum())
        return dict(s=sid, a=aid, d=k, households=hh,
                    delivered=float((v * W)[m2].sum()),
                    gain_pct_income=(float((v[kp] * W[kp]).sum()) / inc_tot
                                     if inc_tot > 0 else None))

    decile_cells = []
    for sid, v in vec.items():
        for aid, mk in broad_masks.items():
            mk = np.asarray(mk)
            for k in range(1, 11):
                decile_cells.append(_dec_row(sid, aid.split()[0], k, v, mk & (dec == k)))
        # Narrow archetypes too, to show where each burdened archetype sits in the statewide income distribution.
        for aid, mk in narrow_masks.items():
            mk = np.asarray(mk)
            for k in range(1, 11):
                decile_cells.append(_dec_row(sid, aid.split()[0], k, v, mk & (dec == k)))
        for k in range(1, 11):
            decile_cells.append(_dec_row(sid, "ALL", k, v, dec == k))

    # ---- narrow: the archetypal household ----------------------------
    base_narrow = A.profile(d, narrow_masks, m.base, order=list(narrow_masks))
    # ---- dollars delivered, fixed bins ------------------------------
    # One bin set for every scenario and every archetype subset, so the panels
    # compare. Emitted statewide and for each archetype in both families.
    delivered_bins = []
    for sid, sc in scen.items():
        delivered_bins.append(dict(s=sid, a="ALL", family="all",
                                   bins=sc.histogram(ALL, W)))
        for fam, masks in (("broad", broad_masks), ("narrow", narrow_masks)):
            for aid, mk in masks.items():
                mk = np.asarray(mk)
                delivered_bins.append(dict(s=sid, a=aid.split()[0], family=fam,
                                           bins=sc.histogram(mk, W)))

    # ---- burden under each scenario ----------------------------------
    # `burden_cells` is the third burden series, beside the two above.
    # `burden_threshold` is the count still above the 6% line by decile, before
    # and after. 6% NOT 4%: the credit pays the
    # excess above 4% of income up to a maximum, so an uncapped household lands
    # at exactly 4% by construction and a count above 4% would measure how many
    # credits hit a ceiling rather than how many households were relieved.
    burden_cells, burden_threshold = [], []
    for sid, sc in scen.items():
        dd, cred, _note = scenario_world(sc, d)
        bs = A.net_burden(dd, np.asarray(cred, float))
        for fam, masks in _fam_masks():
            for aid, mk in masks.items():
                burden_cells.append(dict(s=sid, a=aid.split()[0], family=fam,
                                         bins=burden_bins(bs, W, np.asarray(mk))))
        burden_cells.append(dict(s=sid, a="ALL", family="all",
                                 bins=burden_bins(bs, W, ALL)))
        over_now = A.above(burden_now)
        over_new = A.above(bs)
        for k in range(1, 11):
            inb = dec == k
            burden_threshold.append(dict(
                s=sid, d=k,
                now=float(W[inb & over_now].sum()),
                scen=float(W[inb & over_new].sum())))

    narrow_cells = []
    for sid, sc in scen.items():
        dd, cred, note = scenario_world(sc, d)
        pr = A.profile(dd, narrow_masks, cred, order=list(narrow_masks))
        for (_, b0), (_, p1) in zip(base_narrow.iterrows(), pr.iterrows()):
            mk = np.asarray(narrow_masks[b0["archetype"]])
            # Take-up weighted, matching reallocation.net() and
            # homestead_plus.net(): the CREDIT leg is weighted, because a
            # household receives only what it claims; the BILL leg is not,
            # because a rate or exemption change lands whether or not anyone
            # files a return. S14 carries the Homestead Plus regime's own
            # claiming rate rather than today's PTFC rate.
            d_bill = A.counted_tax(dd) - A.counted_tax(d)
            d_credit = np.asarray(cred, float) - m.base
            gain = d_credit * np.asarray(sc.tau, float) - d_bill
            narrow_cells.append(dict(
                s=sid, a=b0["archetype"].split()[0],
                basis=basis_for(note, b0["base_is"]),
                share_better=sc.better(mk, W), share_worse=sc.worse(mk, W),
                med_gain_delivered=A._wmedian(gain[mk], W[mk]),
                mean_gain_delivered=float((gain[mk] * W[mk]).sum() / W[mk].sum()),
                med_tax_base=float(b0["med_tax"]), med_tax_scen=float(p1["med_tax"]),
                burden_now=float(b0["burden_post"]), burden_scen=float(p1["burden_post"]),
                credit_now=float(b0["med_credit"]), credit_scen=float(p1["med_credit"]),
                pct_eligible=float(p1["pct_eligible"]),
                pct_at_cap=float(p1["pct_at_cap"]), pct_at_base=float(p1["pct_at_base"])))

    tot = pd.read_csv(paths.BASELINE_TOTALS)
    tk = pd.read_csv(paths.TAKEUP_DIR / "ptfc_takeup_by_puma.csv")
    cor = pd.read_csv(paths.TAKEUP_DIR / "ptfc_takeup_correlates.csv")
    # One statewide mill measure for every scenario (bundle_geography.mill_summary).
    mills = GEO.mill_summary()

    return dict(
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        threshold=float(A.BURDEN_THRESHOLD),
        income_floor=float(A.INCOME_FLOOR),
        senior_age=int(A.SENIOR_AGE),
        counts=dict(households=float(W.sum()), owners=float(W[m.owner].sum()),
                    renters=float(W[d["renter"].to_numpy()].sum()),
                    eligible=float(W[el].sum()), claimants=float(tk["claimants"].sum()),
                    pums_rows=int(len(d))),
        totals={r["item"].strip(): float(r["dollars"]) for _, r in tot.iterrows()},
        average_mill=mills["average"],
        takeup=dict(statewide=float(tk["claimants"].sum() / tk["eligible"].sum()),
                    derived=m.tau_flat(), by_puma=_rows(tk)),
        correlates=_rows(cor),
        scenarios=[dict(id=k, name=sc.name, group=sc.group,
                        group_label=B.GROUP_LABEL[sc.group],
                        family=sc.family, parameter=sc.parameter,
                        state_cost=sc.state_cost, pool=sc.pool,
                        redirected=sc.redirected,
                        # Credit-only scenarios leave every mill rate unchanged.
                        mill_change=mills["change"].get(k, 0.0),
                        expansion_split=sc.split,
                        delivered=sc.delivered,
                        gaining=float(W.sum()) * sc.better(ALL, W),
                        losing=float(W.sum()) * sc.worse(ALL, W))
                   for k, sc in scen.items()],
        groups=B.GROUP_LABEL,
        commercial=CA.rows(), commercial_cells=CA.table(),
        deadband=B.DEADBAND,
        # Two geographies, and the schema keeps them apart on purpose.
        # `puma_cells` is every household number, modelled at PUMA level.
        # `towns` is mill rate changes only: the municipal model solves each
        # town exactly, but no household in this model lives in a named town.
        puma_cells=GEO.puma_rows(scen, m),
        puma_order=[dict(puma=int(q), label=GEO.T.PUMA_LABEL[q], rank=i + 1)
                    for i, q in enumerate(GEO.T.PUMA_ORDER)],
        towns=GEO.town_rows(),
        town_mill_scenarios=GEO.MILL_SCENARIOS,
        # One worked household per archetype, in a real town, at 100% take-up.
        # Everything else in this file is take-up weighted at the measured
        # rate, so a view must never put the two in one table unlabelled.
        vignettes=[{k: v for k, v in r.items() if not k.startswith("_")}
                   for r in picks.drop(columns=["_mask"]).to_dict("records")],
        vignette_cells=VIG.relief(picks, scen, m),
        vignette_takeup=1.0,
        delivered_bins=delivered_bins,
        bin_labels=list(B.BIN_LABELS),
        bin_edges=[None if not np.isfinite(e) else float(e)
                   for e in B.BIN_EDGES],
        broad=_rows(A.profile(d, broad_masks, m.base, tau=m.tau_h,
                              order=list(broad_masks))),
        narrow=_rows(base_narrow),
        broad_logic=A.BROAD_LOGIC, narrow_logic=A.NARROW_LOGIC,
        broad_cells=broad_cells, narrow_cells=narrow_cells,
        decile_cells=decile_cells, decile_cuts=dec_cuts,
        burden_bin_labels=BURDEN_LABELS,
        burden_bin_edges=list(BURDEN_EDGES),
        burden_threshold_pct=float(A.BURDEN_THRESHOLD),
        burden_rows=burden_rows,
        burden_cells=burden_cells,
        burden_threshold=burden_threshold,
        burden_undefined=burden_undefined,
        archetype_areas=archetype_areas,
        narrow_notes=A.narrow_notes(d, narrow_masks, m.base))


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else paths.OUTPUT
    out.mkdir(parents=True, exist_ok=True)
    data = build()
    (out / "dashboard.json").write_text(json.dumps(data, allow_nan=False), encoding="utf-8")

    # Reconciliation, printed every run: the broad columns must tile the
    # per-scenario delivered totals.
    pub = {r["id"]: r["delivered"] for r in data["scenarios"]}
    worst = 0.0
    for sid, want in pub.items():
        got = sum(c["delivered"] for c in data["broad_cells"] if c["s"] == sid)
        worst = max(worst, abs(got - want))
        print("  #%-3s cells $%8.2fm  total $%8.2fm" % (sid, got / 1e6, want / 1e6))
    assert worst < 1.0, "broad cells do not tile the scenario totals (max $%.2f)" % worst
    n_s, n_a = len(data["scenarios"]), len(data["broad"]) + len(data["narrow"])
    cells = len(data["broad_cells"]) + len(data["narrow_cells"])
    assert n_s == len(B.ORDER), ("expected %d scenarios (S1-S19), got %d"
                                 % (len(B.ORDER), n_s))
    assert cells == n_s * n_a, ("expected %d scenario-by-archetype cells, got %d"
                                % (n_s * n_a, cells))
    print("OK  %d scenarios x %d archetypes = %d cells" % (n_s, n_a, cells))
    assert len(data["puma_cells"]) == n_s * 10, "puma block is not %d x 10" % n_s
    want = n_s * (1 + n_a)
    assert len(data["delivered_bins"]) == want, (
        "expected %d histogram rows, got %d" % (want, len(data["delivered_bins"])))
    # Every histogram must account for every household in its subset, or a
    # panel silently drops people. Checked here rather than trusted.
    for r in data["delivered_bins"]:
        if r["a"] == "ALL":
            assert abs(sum(r["bins"]) - data["counts"]["households"]) < 1.0, r["s"]
    assert len(data["vignettes"]) == n_a, "one vignette per archetype"
    assert len(data["vignette_cells"]) == n_s * n_a, "a worked example per cell"
    towns = {v["town"] for v in data["vignettes"]}
    assert len(towns) == n_a, "vignette towns must be distinct"
    assert len({v["puma"] for v in data["vignettes"]}) == 10, "all ten areas"
    print("OK  %d vignettes in %d towns across %d areas, %d worked examples"
          % (len(data["vignettes"]), len(towns),
             len({v["puma"] for v in data["vignettes"]}),
             len(data["vignette_cells"])))
    miss = [t["town"] for t in data["towns"] if t.get("s1") is None]
    print("OK  %d PUMA cells, %d towns (%d without a homestead mill change)"
          % (len(data["puma_cells"]), len(data["towns"]), len(miss)))
    print("OK  max discrepancy $%.4f  ->  %s" % (worst, out / "dashboard.json"))


if __name__ == "__main__":
    main()
