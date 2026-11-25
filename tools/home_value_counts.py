#!/usr/bin/env python3
"""Rebuild the home-value counts behind the homestead value cap.

The homestead scenarios need to know how many owner-occupied homes are worth
less than a proposed exemption, because a home cannot be exempted above its
own value. The model reads that from data/derived/home_value_counts.json, which
ships with counts from licensed ATTOM property records. This script rebuilds
the file from any list of owner-occupied homestead properties, such as an
assessor's or MRS parcel extract, so the licensed records are not needed.

Input: a CSV with one row per owner-occupied home and a column of just
(market) values in dollars, optionally with a weight column.

    python tools/home_value_counts.py homes.csv --value-column just_value
    python tools/home_value_counts.py homes.csv --value-column v --weight-column w --out counts.json

By default it overwrites data/derived/home_value_counts.json. Run `make` after.
Only the counts are written, never the rows.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import paths  # noqa: E402
import he_resolve_net as H  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv", type=Path, help="one row per owner-occupied home")
    ap.add_argument("--value-column", required=True, help="column of just values, in dollars")
    ap.add_argument("--weight-column", help="optional column of weights")
    ap.add_argument("--source", help="a note on where the values come from, kept in the file")
    ap.add_argument("--out", type=Path, default=paths.HOME_VALUE_COUNTS)
    a = ap.parse_args(argv)

    cols = [a.value_column] + ([a.weight_column] if a.weight_column else [])
    d = pd.read_csv(a.csv, usecols=cols)
    v = pd.to_numeric(d[a.value_column], errors="coerce")
    w = pd.to_numeric(d[a.weight_column], errors="coerce") if a.weight_column else None
    out = H.value_cap_counts(v, w)
    if a.source:
        out["source"] = a.source
    a.out.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{len(d):,} rows read; {out['n']:,.0f} homes at $25,000 or more, "
          f"{out['at_or_above_100000']:,.0f} at $100,000 or more; wrote {a.out}")


if __name__ == "__main__":
    main()
