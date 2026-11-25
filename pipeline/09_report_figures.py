#!/usr/bin/env python3
"""Print the Technical Report's figures that are not in output/dashboard.json.

Most of the report's figures are in dashboard.json, which step 06 writes. This
step computes the rest from the same code and data, so that a run of the model
reproduces every figure in the report, and the check can be repeated after any
update: change the data, run `make`, then compare this output and
dashboard.json with the report.

The figures are printed under the report's section headings, in its order, at
the precision the report quotes them or finer. Not printed:

- the Validation section's comparisons with MRS and DAFS, which
  `make validate` (07_validate.py) prints;
- figures from outside the model: the ATTOM data vintage, the Time Trends
  report, the Task Force's votes, the credit's expansion history, and the
  commercial archetypes' revenue estimates.

Prints only. It rebuilds the scenarios as step 06 does, which rewrites their
town tables in data/derived/scenarios with the same contents. Run with
`make report`.
"""
import sys
import warnings
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import archetypes as A            # noqa: E402
import bundle_geography as GEO    # noqa: E402
import bundle_scenarios as B      # noqa: E402
import ceiling_redesign as C      # noqa: E402
import congregate_care as CC      # noqa: E402
import fund_totals as F           # noqa: E402
import he_resolve_net as H        # noqa: E402
import homestead_plus as HP       # noqa: E402
import paths                      # noqa: E402
import ptfc_engine as E           # noqa: E402
import ptfc_recalibrate as R      # noqa: E402
import ptfc_takeup as T           # noqa: E402
import reallocation as RA         # noqa: E402

BASES = ("base_single", "base_hoh_one", "base_joint_multi", "base_senior")
BASE_LABEL = ("single filer", "couple or one dependent", "with dependents", "65 and over")
REGION_LABEL = {"Portland": "Greater Portland", "Service": "Service centers",
                "South": "Southern coast", "Rural": "Rural Maine"}


# ------------------------------------------------------------------ printing
def head(title):
    print("\n" + title + "\n" + "-" * len(title))


def row(label, value):
    print("  %-64s %s" % (label, value))


def usd(x):
    return "$" + format(round(float(x)), ",")


def usd_m(x):
    return ("-" if x < 0 else "") + "$%.1fm" % (abs(float(x)) / 1e6)


def pct(x, nd=1):
    return "%.*f%%" % (nd, 100 * float(x))


def num(x):
    return format(round(float(x)), ",")


def wmed(x, w):
    return A._wmedian(np.asarray(x, float), np.asarray(w, float))


# ------------------------------------------------------------------ sections
def definitions(m, d, W):
    head("How the model works: definitions")
    inc = d["income"].to_numpy(float)
    ren = d["renter"].to_numpy(bool)
    row("Median household income", usd(wmed(inc, W)))
    ca = d["rent_annual"].to_numpy(float)
    ga = d["rent_gross_annual"].to_numpy(float)
    r = ren & np.isfinite(ca) & (ga > 0)
    row("Contract rent as a share of gross rent, all renters", pct((ca[r] * W[r]).sum() / (ga[r] * W[r]).sum()))
    counted = A.RENT_SHARE * CC.rent_for_credit(d)
    row("Median renter's counted property tax", usd(wmed(counted[ren], W[ren])))
    care = CC.flag(d)
    row("Rent including care fees: survey records", num(care.sum()))
    row("Rent including care fees: households", num(W[care].sum()))
    z = inc <= 0
    row("Households with income of zero or less", num(W[z].sum()))
    row("  as a share of all households", pct(W[z].sum() / W.sum()))
    row("  share of them eligible for the Fairness Credit", pct(W[z & (m.base > 0)].sum() / W[z].sum(), 0))
    row("Households above 6%, every eligible household claiming", num(W[A.burdened(d, m.base)[0]].sum()))
    row("Households above 6%, at today's claiming rates",
        num(W[A.above(A.net_burden(d, m.base * m.tau_h))].sum()))


def geography(d, W):
    head("How the model works: survey areas and regions")
    puma = d["PUMA"].to_numpy()
    by = pd.Series(W).groupby(puma).sum()
    for q in T.PUMA_ORDER:
        row("Households, %s (%d)" % (T.PUMA_LABEL[q], q), num(by[q]))
    reg = pd.Series(W).groupby([A.REGIONS[int(q)] for q in puma]).sum()
    for k in ("Portland", "Service", "South", "Rural"):
        row("Share of households, %s" % REGION_LABEL[k], pct(reg[k] / W.sum()))


def homesteads(d, W):
    head("Homestead participation")
    hp = T.homestead_by_puma()
    hs, own = hp["homesteads"].sum(), hp["owner_hh"].sum()
    row("Homesteads, 2024 MVR", num(hs))
    row("Owner-occupied households, survey", num(own))
    row("Homestead rate, statewide", pct(hs / own))
    for q in T.PUMA_ORDER:
        row("Homestead rate, %s (%d)" % (T.PUMA_LABEL[q], q), pct(hp.loc[q, "homestead_share"]))
    row("Owner households without a homestead", num(own - hs))
    moved = d["owner"].to_numpy(bool) & (d["MV"].to_numpy() == 1)
    row("Owners who moved in within the last 12 months", num(W[moved].sum()))
    row("  as a share of owner households without a homestead", pct(W[moved].sum() / (own - hs), 0))


def claiming(m, d, W):
    head("Participation and claiming rates")
    tk = T.takeup_by_puma()
    row("Claiming rate, statewide", pct(tk["claimants"].sum() / tk["eligible"].sum()))
    for q in T.PUMA_ORDER:
        row("Claiming rate, %s (%d)" % (T.PUMA_LABEL[q], q), pct(tk.loc[q, "takeup_pct"] / 100))
    raw = T._raw_ptfc_town()
    unnamed = raw[raw["town"].isna() & raw["county"].notna() & (raw["county"] != "NAN")]
    for _, r in unnamed.iterrows():
        row("MRS file, %s: claimants" % r["county"].lower(), num(r["n_ptfc"]))
        row("MRS file, %s: credit" % r["county"].lower(), usd(r["amt_ptfc"]))
    sup = T.suppressed_allocation(raw)
    row("Municipalities the withheld claimants are spread across", num(len(sup)))
    row("  of which allocated the maximum of nine", num((sup["n_ptfc"] >= T.SUPPRESSED_CAP - 1e-9).sum()))
    tot = T.mrs_file_totals()
    row("Claimants placed in Maine, used for claiming rates", num(tot["claimants"]))
    row("Credit paid to them", usd(tot["credit"]))
    el = lambda p: W[E.credit(d, p) > 0].sum()
    t24 = T.takeup_by_puma(params=E.TY2024)
    row("Eligible households, tax year 2024 law", num(el(E.TY2024)))
    row("Claiming rate on tax year 2024 eligibility", pct(t24["claimants"].sum() / t24["eligible"].sum()))
    row("Eligible households, tax year 2025 law (used for claiming rates)", num(el(E.TY2025)))
    tau24 = np.array([t24["takeup_pct"].to_dict()[q] / 100 for q in d["PUMA"]])
    lower = 1 - (m.base * m.tau_h * W).sum() / (m.base * tau24 * W).sum()
    row("Credit delivered at scenario claiming rates, below 2024-matched", pct(lower))


def current_law(d, W):
    head("Current law and the 2024 data")
    row("Maximum credit under 65, tax year 2024 / 2026",
        "%s / %s" % (usd(E.TY2024.cap_under65), usd(E.TY2026.cap_under65)))
    for f, lab in zip(BASES, BASE_LABEL):
        row("Benefit base, %s, tax year 2024 / 2026" % lab,
            "%s / %s" % (usd(getattr(E.TY2024, f)), usd(getattr(E.TY2026, f))))
    row("Eligible households, tax year 2026 law", num(W[E.credit(d, E.TY2026) > 0].sum()))


def survey_years(d, W):
    head("Why we use the observed household data")
    own = d["owner"].to_numpy(bool)
    inc = d["income"].to_numpy(float)
    hv = pd.to_numeric(d["home_value"], errors="coerce").to_numpy(float)
    tax = d["prop_tax"].to_numpy(float)
    yr = d["SERIALNO"].str[:4].to_numpy()
    c25 = E.credit(d, E.TY2025)
    nb = A.net_burden(d, c25)
    print("  Survey year | median home value | median property tax | eligible (2025 law) | "
          "median burden | median income")
    hv_by = {}
    for y in sorted(set(yr)):
        k = yr == y
        ko = k & own & np.isfinite(hv) & (hv > 0)
        kt = k & own & (tax > 0)
        kb = k & np.isfinite(nb)
        hv_by[y] = wmed(hv[ko], W[ko])
        print("  %-11s | %17s | %19s | %19s | %13s | %s"
              % (y, usd(hv_by[y]), usd(wmed(tax[kt], W[kt])),
                 pct(W[k & (c25 > 0)].sum() / W[k].sum()), pct(wmed(nb[kb], W[kb]), 2),
                 usd(wmed(inc[k], W[k]))))
    ys = sorted(hv_by)
    row("Change in median home value, %s to %s" % (ys[0], ys[-1]), pct(hv_by[ys[-1]] / hv_by[ys[0]] - 1, 0))
    # Survey home values, as the report's sentence is about the survey data. The
    # model's own cap (he_resolve_net.cap_ratio) uses the ATTOM counts instead.
    for label, (dex, *_) in R.HE_SCENARIOS.items():
        if label.startswith(("#1", "#3")):
            ex = R.CURRENT_EXEMPTION + dex
            row("Owners whose home is worth less than the S%s exemption (%s)" % (label[1], usd(ex)),
                pct(W[own & (hv < ex)].sum() / W[own].sum()))


def category_a(d, W):
    head("Validation, Category A (Categories B and C: make validate)")
    own = d["owner"].to_numpy(bool)
    hv = pd.to_numeric(d["home_value"], errors="coerce").to_numpy(float)
    tax = d["prop_tax"].to_numpy(float)
    row("Owner-occupied share of households", pct(W[own].sum() / W.sum()))
    row("Households with someone under 18", pct(W[d["age_youngest"].to_numpy() < 18].sum() / W.sum()))
    row("Households with someone 65 or over", pct(W[d["age_oldest"].to_numpy() >= 65].sum() / W.sum()))
    k = own & np.isfinite(hv)
    row("Median owner-occupied home value", usd(wmed(hv[k], W[k])))
    row("Mean property tax, owner-occupiers", usd((tax[own] * W[own]).sum() / W[own].sum()))
    mvr = T.load_mvr(T.MVR_YEAR)
    for c in ("hstead_count", "hstead_totalpval", "hstead_eval", "mill_rate"):
        mvr[c] = pd.to_numeric(mvr[c], errors="coerce")
    bill = ((mvr["hstead_totalpval"] - mvr["hstead_eval"]) * mvr["mill_rate"]).sum() / mvr["hstead_count"].sum()
    row("Average bill per homestead implied by the 2024 MVR", usd(bill))


def limitations(m, d, W):
    head("Limitations")
    # Town mill rates against town median income, within each survey area:
    # towns split at the area's median town income, rates homestead-weighted.
    mvr = T.load_mvr(T.MVR_YEAR)
    for c in ("hstead_count", "mill_fv"):
        mvr[c] = pd.to_numeric(mvr[c], errors="coerce")
    acs = pd.read_csv(paths.MUNI_ACS)
    acs["key"] = T._key(acs["MUNI"])
    acs["income"] = pd.to_numeric(acs["median_hh_income_display"].astype(str)
                                  .str.replace(r"[$,]", "", regex=True), errors="coerce")
    puma = T.load_xwalk().drop_duplicates("key").set_index("key")["PUMACE20"]
    f = mvr[["key", "mill_fv", "hstead_count"]].merge(acs[["key", "income"]], on="key").dropna()
    f["puma"] = f["key"].map(puma)
    gaps = {}
    for q, g in f.dropna(subset=["puma"]).groupby("puma"):
        poor = g["income"] < g["income"].median()
        hw = lambda s: (s["mill_fv"] * s["hstead_count"]).sum() / s["hstead_count"].sum()
        gaps[int(q)] = 1000 * (hw(g[poor]) - hw(g[~poor]))
    print("  Full-value mill rate of the poorer half of towns less the richer half, by survey")
    print("  area (towns split at the area's median town income, rates homestead-weighted):")
    for q in T.PUMA_ORDER:
        row("  " + T.PUMA_LABEL[q], "%+.1f mills" % gaps[q])
    row("  average over the ten survey areas", "%+.1f mills" % np.mean(list(gaps.values())))
    inc = d["income"].to_numpy(float)
    p4 = R.scale_bases(m.solve_multiplier(), m.p0)
    dl = m.delta(p4)
    g = dl * m.tau_h * W
    row("Scenario 4: share of new relief to households above $60,000", pct(g[inc > 60_000].sum() / g.sum(), 0))
    up = g.sum() + (dl * (1 - m.tau_h) * W)[(dl > 0) & (inc > 60_000)].sum()
    row("Scenario 4: cost if every gaining household above $60,000 claimed", usd_m(up))


def cost35(m, d, W):
    head("Scenarios 1 to 8")
    rs = F.revenue_sharing()
    ptfc = float((m.base * m.tau_h * W).sum())
    hre = RA.gross_pool("12")
    total = rs["total"] + hre + ptfc
    row("Revenue Sharing I / II", "%s / %s" % (usd_m(rs["rev_i"]), usd_m(rs["rev_ii"])))
    row("Homestead reimbursement", usd_m(hre))
    row("Fairness Credit delivered", usd_m(ptfc))
    row("Relief programs in total", usd_m(total))
    row("$35 million as a share of that", pct(35e6 / total))
    k = m.solve_multiplier()
    p4 = R.scale_bases(k, m.p0)
    row("S4: benefit bases raised by", pct(k - 1, 1))
    row("S4: income ceiling, single filer, now / under S4",
        "%s / %s" % (usd(m.p0.base_single / m.p0.rate_income), usd(p4.base_single / p4.rate_income)))
    row("S4: income ceiling, 65 and over, now / under S4",
        "%s / %s" % (usd(m.p0.base_senior / m.p0.rate_income), usd(p4.base_senior / p4.rate_income)))
    row("S5: cost of doubling the maximum credits alone",
        usd_m(m.real_puma(replace(m.p0, cap_under65=3_000.0, cap_senior=4_000.0))))
    row("S5: cost of removing the maximum credits", usd_m(m.real_puma(replace(m.p0, cap_under65=1e9, cap_senior=1e9))))
    r5 = m.solve_offset(3_000.0, 4_000.0)
    p5 = replace(m.p0, rate_income=r5, cap_under65=3_000.0, cap_senior=4_000.0)
    row("S5: burden threshold", pct(r5, 2))
    row("S5: households newly eligible", num(W[(m.base <= 0) & (E.credit(d, p5) > 0)].sum()))
    row("S6: benefit bases raised by", pct(R.solve_hybrid_base(m, 1.5) - 1, 1))
    rd = C.Redesign(m)
    row("S7, S8: cost of a 6% ceiling for every household", usd_m(rd.cost(C.Design("everyone"))))
    s7, s8 = C.recommended(rd)
    row("S7: ceiling payment phases out between", "%s and %s" % (usd(s7.gtaper[0]), usd(s7.gtaper[1])))
    row("S8: maximum ceiling payment / home value counted", "%s / %s" % (usd(s8.cap), usd(s8.apportion)))


def mill_rows():
    head("Mill rates in the scenario tables (also in dashboard.json)")
    s = GEO.mill_summary()
    row("Current", "Average %.2f mills" % s["average"])
    for sid, c in s["change"].items():
        word = "Increase" if c > 0 else "Decrease"
        row("Scenario %s" % sid, "%s of %.2f mills (%s%.2f%%)"
            % (word, abs(c) * s["average"], "+" if c > 0 else "-", abs(100 * c)))


def realloc(m, scen):
    head("Scenarios 9 to 13")
    splits = {}
    for sid in RA.SCENARIOS:
        e = RA.Expansion(m, sid)
        p = e.solve()["params"]
        sp = scen[sid].split
        splits[sid] = sp
        print("  Scenario %s" % sid)
        row("  money freed", usd_m(e.gross_pool))
        row("  reimbursements at the higher rates, homestead / equipment",
            "%s / %s" % (usd_m(e.he_float), usd_m(e.bete_float)))
        row("  left for the Fairness Credit", usd_m(e.pool))
        row("  benefit bases / maximum credits raised by",
            "%s / %s" % (pct(p.base_single / m.p0.base_single - 1), pct(p.cap_under65 / m.p0.cap_under65 - 1)))
        row("  benefit bases", " / ".join(usd(round(getattr(p, f), -1)) for f in BASES))
        row("  maximum credits, under 65 / 65 and over",
            "%s / %s" % (usd(round(p.cap_under65, -1)), usd(round(p.cap_senior, -1))))
        row("  burden threshold", pct(p.rate_income, 2))
        row("  expansion bought by maximum credits / bases / threshold",
            " / ".join(pct(sp[g], 0) for g in RA.SPLIT_GROUPS))
    for g, lab in zip(RA.SPLIT_GROUPS, ("maximum credits", "benefit bases", "burden threshold")):
        v = [splits[s][g] for s in splits]
        row("Share bought by the %s, lowest to highest" % lab, "%s to %s" % (pct(min(v), 0), pct(max(v), 0)))
    e = RA.Expansion(m, "13")
    p = e.solve()["params"]
    row("S13: maximum credit under 65 / single-filer benefit base",
        "%s / %s" % (usd(round(p.cap_under65, -1)), usd(round(p.base_single, -1))))


def homestead_plus(m):
    head("Scenario 14")
    hp = HP.HomesteadPlus(m)
    row("Fairness Credit abolished", usd_m((m.base * m.tau_h * m.W).sum()))
    t = pd.read_csv(paths.SCENARIO_DIR / GEO.HP_FILE)
    row("Exempt value returned to the tax base", "$%.1f billion" % (t["EV"].sum() / 1e9))
    row("State funds freed / Homestead Plus cost", "%s / %s" % (usd_m(hp.pool), usd_m(hp.cost)))
    row("Returned to the State", usd_m(hp.pool - hp.cost))


def packages(scen):
    head("Scenarios 15 to 19")
    rev_i = F.revenue_sharing()["rev_i"]
    red = []
    for sid in ("15", "16", "17", "18", "19"):
        s, f = scen[sid], scen[sid].funding
        red.append(s.redirected)
        print("  Scenario %s" % sid)
        row("  Revenue Sharing I cut, and share of the fund",
            "%s, %s" % (usd_m(f["revenue_sharing_cut"]), pct(f["revenue_sharing_cut"] / rev_i, 0)))
        row("  Fairness Credit expansion", usd_m(f["credit"]))
        row("  change in homestead reimbursement", usd_m(f["homestead_reimbursement"]))
        row("  change in business equipment reimbursement", usd_m(f["bete_reimbursement"]))
        row("  money redirected (cut plus reimbursement rate saving)", usd_m(s.redirected))
    row("Money redirected, lowest to highest", "%s to %s" % (usd_m(min(red)), usd_m(max(red))))


def archetypes(m, d, W):
    head("Archetypes (figures not in the archetype profiles in dashboard.json)")
    inc = d["income"].to_numpy(float)
    o = np.argsort(inc, kind="stable")
    dec = np.empty(len(d), int)
    dec[o] = np.clip((np.cumsum(W[o]) / W.sum() * 10).astype(int), 0, 9) + 1
    mv = d["MV"].to_numpy()
    age = d["age_head"].to_numpy()
    rent = d["rent_annual"].to_numpy(float)
    before = A.net_burden(d, np.zeros(len(d)))
    after = A.net_burden(d, m.base)
    # The code names the representative archetypes B1-B6 and the burdened N1-N7;
    # the report calls them R1-R6 and B1-B7.
    masks = {"R" + k[1:].split()[0]: v for k, v in A.broad(d).items()}
    masks.update({"B" + k[1:].split()[0]: v for k, v in A.narrow_rules(d, m.base)[0].items()})
    print("  Archetype | income p10 | income p90 | top 4 deciles | moved in last 4 years | other")
    for name, mk in masks.items():
        mk = np.asarray(mk, bool)
        w = W[mk]
        x = inc[mk]
        q = np.argsort(x)
        cw = np.cumsum(w[q]) / w.sum()
        p10, p90 = (np.interp(t, cw, x[q]) for t in (0.1, 0.9))
        other = []
        if name.startswith("R3"):
            a = age[mk]
            other.append("aged 50-64 %s, under 40 %s" % (pct(w[(a >= 50) & (a < 65)].sum() / w.sum()),
                                                          pct(w[a < 40].sum() / w.sum())))
        if name.startswith("R6"):
            other.append("above 4%% before / after relief %s / %s"
                         % (pct(w[A.above(before[mk], 0.04)].sum() / w.sum(), 0),
                            pct(w[A.above(after[mk], 0.04)].sum() / w.sum(), 0)))
        if d["renter"].to_numpy(bool)[mk].all():
            other.append("rent above income %s" % pct(w[rent[mk] > x].sum() / w.sum(), 0))
        print("  %-9s | %10s | %10s | %13s | %21s | %s"
              % (name, usd(round(p10, -2)), usd(round(p90, -2)),
                 pct(w[dec[mk] >= 7].sum() / w.sum()),
                 pct(w[np.isin(mv[mk], [1, 2, 3])].sum() / w.sum(), 0), "; ".join(other)))


def main():
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    m = R.Model()
    d, W = m.df, m.W.astype(float)
    print("Technical Report figures not in output/dashboard.json, computed from this run.")
    definitions(m, d, W)
    geography(d, W)
    homesteads(d, W)
    claiming(m, d, W)
    current_law(d, W)
    survey_years(d, W)
    category_a(d, W)
    limitations(m, d, W)
    cost35(m, d, W)
    scen = B.load(m)
    mill_rows()
    realloc(m, scen)
    homestead_plus(m)
    packages(scen)
    archetypes(m, d, W)


if __name__ == "__main__":
    main()
