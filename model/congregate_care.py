"""Congregate and assisted living: counting only the occupancy portion of a fee.

PUMS records one rent figure per household. For a resident of an assisted
living or residential care facility that figure is the whole fee, which combines
a room with meals, housekeeping, utilities and personal care. 36 M.R.S. 5219-KK
counts 15% of rent as property tax, and MRS Rule 813 .05(A) allows that only on
rent "paid solely for the right of occupancy". Applying 15% to the whole fee
would count a care charge as property tax.

Senior renter households (head-or-spouse 65+, the test the statute uses) with
annual contract rent at or above FEE_THRESHOLD have the rent that counts toward
the credit and the burden reduced to OCCUPANCY_SHARE of the fee. `rent_annual`
keeps the fee and is what published rent figures report; `rent_counted` is the
occupancy portion used by every credit and burden calculation, read through
`rent_for_credit`.

- OCCUPANCY_SHARE = 30% sits between two independent anchors. The MaineCare
  room-and-board rate for Adult Family Care Homes ($1,352 a month, $16,224 a
  year) is 36.5% of the $44,469 median fee in this group, and still includes
  meals, which Rule 813 excludes. The median local contract rent of renters in
  the same PUMA and household size gives an occupancy share of 28% for seniors
  living alone (interquartile 24% to 30%).
- FEE_THRESHOLD = $36,000 falls inside an empty band: senior renter rents stop
  at $33,000 and resume at $39,000, so the threshold separates two populations
  and a hard classifier is used rather than a taper.
- Seniors only: under-65 high-fee renters cannot be told apart from renters of
  expensive market housing, so the adjustment is limited to the cases where the
  congregate-care reading is strong.

Only residents who reported the whole facility fee can be identified; one who
reported only a room charge is already measured correctly. The adjustment
therefore catches some congregate-care households and misses others.
"""

import numpy as np

OCCUPANCY_SHARE = 0.30     # anchored at 28% imputed and 36.5% room-and-board
FEE_THRESHOLD = 36_000.0   # inside the empty $33,000-$39,000 band


def _col(df, name, default=0.0):
    """Column `name` as floats with NaN replaced by `default`; None if absent."""
    if name in getattr(df, "columns", ()):
        return np.nan_to_num(np.asarray(df[name], dtype=float), nan=default)
    return None


def flag(df) -> np.ndarray:
    """Households whose reported rent is read as a congregate-care fee.

    Senior renters at or above the fee threshold. A frame without a `senior`
    column flags nobody; one without `renter` is treated as all renters.
    """
    rent = _col(df, "rent_annual")
    if rent is None:
        return np.zeros(len(df), dtype=bool)
    cols = getattr(df, "columns", ())
    if "senior" not in cols:
        return np.zeros(len(df), dtype=bool)
    senior = np.asarray(df["senior"]).astype(bool)
    renter = (np.asarray(df["renter"]).astype(bool) if "renter" in cols
              else np.ones(len(df), dtype=bool))
    return senior & renter & (rent >= FEE_THRESHOLD)


def counted_rent(df) -> np.ndarray:
    """Rent for the right of occupancy: the fee, haircut where flagged."""
    rent = _col(df, "rent_annual")
    if rent is None:
        return np.zeros(len(df), dtype=float)
    return np.where(flag(df), rent * OCCUPANCY_SHARE, rent)


def rent_for_credit(df) -> np.ndarray:
    """Rent for the credit. Every credit and burden calculation reads rent here.

    Uses the `rent_counted` column that `ptfc_takeup.load_pums` writes, and
    derives it when the column is absent, so any frame gives the same result.
    """
    rc = _col(df, "rent_counted", default=np.nan)
    if rc is not None:
        return np.nan_to_num(rc)
    return counted_rent(df)
