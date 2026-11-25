#!/usr/bin/env python3
"""Reproduce the Technical Report's checks of current relief spending.

Fairness Credit. The report compares the credit the model delivers with what
Maine Revenue Services paid. MRS's claimant file is for tax year 2024, so this
check applies TY2024 law and recalibrates take-up on TY2024 eligibility
(claimants divided by eligible households, by survey area). The scenarios
instead calibrate on TY2025 eligibility and run on TY2026 law (see ptfc_engine).

Homestead Exemption. A consistency check, not an independent test: the
homestead rate and the tax rate it uses both come from the Municipal Valuation
Return it is compared with, so only the cap at each home's value is new
information. The same calculation with the full $25,000 for every homestead is
printed alongside to show that.

Changes. The cost of five changes against MRS's own costings: LD 2212 and
MRS's prototypes of Scenarios 1, 3, 5 and 6. MRS's figures are read from its
workbooks in data/raw, except the two homestead prototypes, which MRS sent by
email and are recorded below.

Prints the comparisons and writes nothing. Run with `make validate`.
"""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import baseline_programs as B   # noqa: E402
import he_resolve_net as H      # noqa: E402
import paths                    # noqa: E402
import ptfc_engine as E         # noqa: E402
import ptfc_recalibrate as R    # noqa: E402
import ptfc_takeup as T         # noqa: E402

# What MRS reported to the Task Force for TY2024 in September 2026. It is
# higher than the town-level file, most likely because of TY2024 returns filed
# or amended after that file was extracted.
MRS_REPORTED_TO_TASK_FORCE = 117.5e6

# DAFS's estimate of the FY2025 homestead reimbursement (15 December 2025,
# https://legislature.maine.gov/doc/12343).
DAFS_HOMESTEAD_FY2025 = 85.1e6

# MRS's prototypes of Scenarios 1 and 3: exemption, reimbursement rate, and the
# State's total cost including the other reimbursements that float with the
# mill. Priced for the 2025 property tax year; sent to the project by email.
MRS_HOMESTEAD_PROTOTYPES = {
    "Prototype of Scenario 1: exemption $35,275 at 76%": (35_275.0, 0.76, 34_358_600.0),
    "Prototype of Scenario 3: exemption $52,500 at 50%": (52_500.0, 0.50, 34_311_700.0),
}


def ptfc_validation(law=E.TY2024) -> dict:
    """Credit delivered under `law`, with take-up calibrated on the same law."""
    t = T.takeup_by_puma(params=law)
    b = B.Baseline(R.Model(takeup=t), params=law)
    return dict(
        eligible=float(t["eligible"].sum()),
        claimants=float(t["claimants"].sum()),
        mrs_paid=float(t["credit_paid"].sum()),
        delivered=float((b.ptfc() * b.W).sum()),
    )


def homestead_check() -> dict:
    """The State's TY2024 homestead reimbursement as the household side of the
    model computes it: 76% of each survey area's full-value mill times the
    exemption, min($25,000, home value), weighted by the area's homestead rate."""
    m = R.Model()
    hv = pd.to_numeric(m.df["home_value"], errors="coerce").fillna(0.0).to_numpy()
    own = m.df["owner"].to_numpy().astype(bool)
    w = (B.REIMB * m.W * m.hshare_h * m.mill_h)[own]
    return dict(
        model=float((w * np.minimum(25_000.0, hv[own])).sum()),
        full_exemption=float((w * 25_000.0).sum()),
        mvr=float(H.load_mvr()["cur_HE_Reimb"].sum()),   # TRCF Line 21
    )


def _mrs_cell(path, sheet, ref, year_ref, year):
    """One figure from an MRS workbook, after checking the row or column is for
    the expected tax year."""
    ws = openpyxl.load_workbook(path, data_only=True, read_only=True)[sheet]
    assert int(ws[year_ref].value) == year, (path.name, sheet, year_ref, ws[year_ref].value)
    return float(ws[ref].value)


def fiscal_notes() -> list:
    """The cost of five changes, against MRS's own costings.

    The Fairness Credit changes are priced the way MRS priced them: TY2024 law,
    take-up calibrated on TY2024 eligibility, newly eligible households
    included, and (for MRS's Scenarios C and D) against a baseline that already
    has the $1,500 under-65 maximum. Scenario D's 17.3% applies to each TY2024
    benefit base. The homestead changes are the State's change in homestead and
    BETE reimbursement; MRS also floats renewable energy and veterans'
    reimbursements, about 15% of that leg, which the model does not.
    """
    m = R.Model(takeup=T.takeup_by_puma(params=E.TY2024))

    def ptfc_change(p0, p1):
        b0, b1 = B.Baseline(m, params=p0), B.Baseline(m, params=p1)
        return float(((b1.ptfc() - b0.ptfc()) * b0.W).sum())

    max1500 = replace(E.TY2024, cap_under65=1_500.0)
    scen_c = replace(max1500, cap_under65=3_000.0, cap_senior=4_000.0, rate_income=0.037)
    scen_d = replace(max1500, cap_under65=2_250.0, cap_senior=3_000.0,
                     **{f: getattr(max1500, f) * 1.173 for f in
                        ("base_single", "base_hoh_one", "base_joint_multi", "base_senior")})
    fn, sc = paths.MRS_FISCAL_NOTES, paths.MRS_PTFC_SCENARIOS
    mvr = H.load_mvr()
    rows = [("LD 2212: under-65 maximum $1,000 to $1,500",
             ptfc_change(E.TY2024, max1500),
             _mrs_cell(fn, "Increase <65 PTFC Max to $1500", "B22", "A22", 2024))]
    for label, (ex, rate, mrs) in MRS_HOMESTEAD_PROTOTYPES.items():
        rows.append((label, float(H.gross_cost(mvr, ex, rate) + H.bete_cost(mvr, ex, rate)), mrs))
    rows += [
        ("Prototype of Scenario 5: maximums $3,000/$4,000, threshold 3.7%",
         ptfc_change(max1500, scen_c), _mrs_cell(sc, "Sheet1", "E7", "E3", 2024)),
        ("Prototype of Scenario 6: maximums $2,250/$3,000, bases +17.3%",
         ptfc_change(max1500, scen_d), _mrs_cell(sc, "Sheet1", "E14", "E3", 2024)),
    ]
    return [dict(change=c, model=x, mrs=y) for c, x, y in rows]


def main():
    v = ptfc_validation()
    rate = v["claimants"] / v["eligible"]
    gap_town = v["delivered"] / v["mrs_paid"] - 1
    gap_tf = v["delivered"] / MRS_REPORTED_TO_TASK_FORCE - 1
    print("Property Tax Fairness Credit, TY2024 law, take-up calibrated on TY2024 eligibility")
    print(f"  eligible households                    {v['eligible']:>14,.0f}")
    print(f"  MRS claimants, by town                 {v['claimants']:>14,.0f}")
    print(f"  claiming rate                          {100 * rate:>13.1f}%")
    print(f"  model: credit delivered               ${v['delivered']:>14,.0f}")
    print(f"  MRS: credit paid, by town             ${v['mrs_paid']:>14,.0f}   model {100 * gap_town:+.1f}%")
    print(f"  MRS: reported to the Task Force       ${MRS_REPORTED_TO_TASK_FORCE:>14,.0f}   model {100 * gap_tf:+.1f}%")

    h = homestead_check()
    print()
    print("Homestead Exemption reimbursement, TY2024: a consistency check, not an independent test")
    print(f"  model: exemption capped at home value ${h['model']:>14,.0f}")
    print(f"  MVR 2024, Line 21 (municipalities)    ${h['mvr']:>14,.0f}   model {100 * (h['model'] / h['mvr'] - 1):+.1f}%")
    print(f"  DAFS estimate, FY2025                 ${DAFS_HOMESTEAD_FY2025:>14,.0f}   model {100 * (h['model'] / DAFS_HOMESTEAD_FY2025 - 1):+.1f}%")
    print(f"  full $25,000 for every homestead     ${h['full_exemption']:>14,.0f}   "
          f"{100 * (h['full_exemption'] / h['mvr'] - 1):+.1f}% against the MVR")

    print()
    print("Cost of changes, against MRS's own costings")
    print(f"  {'change':66s}{'model':>14s}{'MRS':>15s}{'gap':>8s}")
    for r in fiscal_notes():
        print(f"  {r['change']:66s} ${r['model']:>12,.0f}  ${r['mrs']:>12,.0f}"
              f"{100 * (r['model'] / r['mrs'] - 1):>+7.1f}%")


if __name__ == "__main__":
    main()
