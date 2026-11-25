"""State relief funds that the reallocation scenarios draw on, read from the data.

Revenue sharing comes from the TOTALS row of the State Treasurer's projections
(`paths.REVENUE_SHARING_PROJECTIONS`): Revenue Sharing I and II for FY2025. The
scenarios use the totals rounded to the nearest $100,000, which is how the
Technical Report states them ($208.5m, $56.1m and $264.6m together). The
totals are a little larger than the sum of the town rows the model matches to
the MVR (Rev I $207.5m), because a few towns in the projections are not
matched; the scenarios size the fund on the Treasurer's own total.

To move the model to a later year, replace the projections file (see
docs/updating.md); these totals follow it.
"""
from functools import lru_cache

import pandas as pd

import paths


@lru_cache(maxsize=None)
def revenue_sharing() -> dict:
    """{'rev_i', 'rev_ii', 'total'}: the Treasurer's projected fund totals."""
    p = pd.read_excel(paths.REVENUE_SHARING_PROJECTIONS, header=5, engine="calamine")
    p.columns = [str(c).replace(chr(10), " ").strip() for c in p.columns]
    col_i = [c for c in p.columns if c.startswith("Rev I Projected")][0]
    col_ii = [c for c in p.columns if c.startswith("Rev II Projected")][0]
    tot = p[p.iloc[:, 0].astype(str).str.strip().str.upper() == "TOTALS"]
    if len(tot) != 1:
        raise ValueError("expected one TOTALS row in the revenue sharing projections")
    rev_i, rev_ii = (round(float(tot[c].iloc[0]) / 1e5) * 1e5 for c in (col_i, col_ii))
    return dict(rev_i=rev_i, rev_ii=rev_ii, total=rev_i + rev_ii)
