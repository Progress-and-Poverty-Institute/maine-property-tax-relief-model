#!/usr/bin/env python3
"""Property Tax Fairness Credit take-up by survey area (PUMA).

Divides the claimants Maine Revenue Services reports by town, aggregated to the
ten PUMAs, by the households the credit formula finds eligible in the ACS
sample. Writes data/derived/takeup/ptfc_takeup_by_puma.csv and
ptfc_takeup_correlates.csv, after checking the result against the State's
published totals.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import paths                # noqa: E402
import ptfc_takeup as T     # noqa: E402


def main():
    paths.TAKEUP_DIR.mkdir(parents=True, exist_ok=True)
    t = T.takeup_by_puma()

    checks = T.verify(t)
    assert checks["pass"].all(), checks[~checks["pass"]]
    xw = T.crosswalk_check(t)
    assert xw["pass"].all(), xw[~xw["pass"]]

    t.to_csv(paths.TAKEUP_DIR / "ptfc_takeup_by_puma.csv")
    T.correlates(t).to_csv(paths.TAKEUP_DIR / "ptfc_takeup_correlates.csv")
    print(f"statewide take-up: {t.claimants.sum():,.0f} claimants / "
          f"{t.eligible.sum():,.0f} eligible = "
          f"{100 * t.claimants.sum() / t.eligible.sum():.1f}%")


if __name__ == "__main__":
    main()
