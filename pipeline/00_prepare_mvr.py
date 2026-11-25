#!/usr/bin/env python3
"""Build the Municipal Valuation Return panel the model reads.

Input: data/raw/mvr_2012_2024.xlsx, one sheet per MVR year ("2012" to "2024"),
each with a row per municipality and, in most years, rows for counties and the
state. Columns are headed by the line numbers on the MRS return: "12" for the
mill rate up to 2021, "Line 12" from 2022, and "TRCF: Line N" for the Tax Rate
Calculation Form lines that the 2022 and later sheets carry.

Output: data/derived/mvr_2012_2024.csv, one row per place and year, with the 52
lines the model uses under stable names (LINES below). The 2022 to 2024 sheets
have no county rows, so county totals are added for those years by summing
their municipalities.

To add a year, add a sheet named for it with the same headings as the 2024
sheet, run `make mvr`, then set ptfc_takeup.MVR_YEAR to the new year and run
`make`. The output file keeps its name.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import paths  # noqa: E402

FIRST_YEAR = 2012
NEW_HEADINGS = 2022      # first sheet with "Line N" headings
BASE = ["Aggregation", "County_ofMuni", "Place"]

# Output name: (heading up to 2021, heading from 2022). None: not on the older
# sheets, so empty for 2012-2021.
LINES = {
    "certified_ratio":     ("3",   "Certified Ratio"),
    "nontaxable_pval":     ("40",  "Line 40"),
    "land_parcels":        ("42",  "Line 42"),
    "total_taxableval":    ("11",  "Line 11"),
    "mill_rate":           ("12",  "Line 12"),
    "real_estate_taxable": ("6",   "Line 6"),
    "commitment":          ("13",  "Line 13"),
    "hstead_max_count":    ("14a", "Line 14a"),   # homesteads at the full exemption
    "hstead_max_val":      ("14b", "Line 14b"),
    "hstead_part_count":   ("14c", "Line 14c"),   # homesteads exempt only in part
    "hstead_part_val":     ("14d", "Line 14d"),
    "hstead_count":        ("14e", "Line 14e"),
    "hstead_eval":         ("14f", "Line 14f"),   # exempt value
    "hstead_totalpval":    ("14g", "Line 14g"),
    "Line 40v":            ("40v", "Line 40v"),
    "Line 40u(3)":         ("40u(3)", "Line 40u(3)"),
    "Line 40s":            ("40s", "Line 40s"),
    "Line 40t(B)":         ("40t(B)", "Line 40t(B)"),
    "last_val":            ("44c", "Line 44c"),   # date of last revaluation
    "val_contractor":      ("44d", "Line 44d"),   # revaluation contractor
    "Line 40k(2)":         (None, "Line 40k(2)"),
    "Expected RevShare":   (None, "TRCF: Line 12"),
    "Other Revs (incl Reimbursements)": (None, "TRCF: Line 13"),
    "Appropriations":      (None, "TRCF: Line 11"),
    "TRCF: Line 22":       (None, "TRCF: Line 22"),   # BETE reimbursement
    "TRCF: Line 21":       (None, "TRCF: Line 21"),   # homestead reimbursement
    "TRCF: Line 15":       (None, "TRCF: Line 15"),   # net to be raised
    "TRCF: Line 7":        (None, "TRCF: Line 7"),    # county tax
    "TRCF: Line 8":        (None, "TRCF: Line 8"),    # municipal appropriation
    "TRCF: Line 9":        (None, "TRCF: Line 9"),    # TIF financing plan amount
    "TRCF: Line 10":       (None, "TRCF: Line 10"),   # local education appropriation
    "TRCF: Line 14":       (None, "TRCF: Line 14"),   # total deductions
    **{f"Line 40{p}": (f"40{p}", f"Line 40{p}") for p in
       ("a(1)", "a(2)", "b", "c", "d", "e", "f", "g", "h", "i", "j(1)", "j(2)")},
    "Line 40k(1)":         ("40k", "Line 40k(1)"),
    **{f"Line 40{p}": (f"40{p}", f"Line 40{p}") for p in ("l", "m", "n", "o", "p", "q", "r")},
}
LINES["Line 40h"] = ("40h", "Line40h")   # no space in the 2022+ heading

# Older sheets whose headings differ: parts of Line 40 were relettered in 2015
# and 2020, and Line 40u(3) first appears in 2020.
OLD_HEADINGS = {
    "Line 40v":    {y: "40u" for y in range(2012, 2020)},
    "Line 40s":    {y: "40t" for y in range(2012, 2015)},
    "Line 40t(B)": {y: "40s(B)" for y in range(2012, 2015)},
    "Line 40u(3)": {y: None for y in range(2012, 2020)},
}

TEXT = BASE
DECIMAL = ["certified_ratio", "mill_rate"]
WHOLE_DOLLARS = ["real_estate_taxable", "commitment", "hstead_totalpval", "hstead_eval",
                 "hstead_count", "total_taxableval", "land_parcels", "nontaxable_pval",
                 "Line 40a(1)", "Line 40a(2)", "Line 40b", "Line 40c", "Line 40d",
                 "Line 40e", "Line 40f", "Line 40g", "Line 40h", "Line 40i",
                 "Line 40j(1)", "Line 40k(1)", "Line 40l", "Line 40m", "Line 40n",
                 "Line 40o", "Line 40p", "Line 40q", "Line 40r", "Line 40s",
                 "Line 40t(B)", "Line 40u(3)", "Line 40v"]


def heading(name: str, year: int):
    if name in OLD_HEADINGS and year in OLD_HEADINGS[name]:
        return OLD_HEADINGS[name][year]
    old, new = LINES[name]
    return new if year >= NEW_HEADINGS else old


def find(df: pd.DataFrame, label):
    """The column headed `label`, ignoring type and surrounding spaces."""
    if label is None:
        return None
    for c in df.columns:
        if str(c).strip() == str(label).strip():
            return c
    return None


def read_year(xls: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    year = int(sheet)
    df = pd.read_excel(xls, sheet_name=sheet)
    for c in BASE:
        if c not in df.columns:
            print(f"  {sheet}: no '{c}' column")
            df[c] = pd.NA
    out = df[BASE].copy()
    for name in LINES:
        label = heading(name, year)
        col = find(df, label)
        if col is None and label is not None:
            print(f"  {sheet}: no '{label}' column for {name}; left empty")
        out[name] = df[col] if col is not None else pd.NA
    out["Year"] = year
    return out


def clean_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in TEXT:
        df[c] = df[c].astype("string").str.strip()
    for c in DECIMAL:
        s = (df[c].astype(str).str.replace(",", "", regex=False)
             .str.replace("$", "", regex=False).str.replace("%", "", regex=False).str.strip())
        df[c] = pd.to_numeric(s, errors="coerce")
    for c in WHOLE_DOLLARS:
        s = df[c].astype(str).str.replace(",", "", regex=False).str.replace("$", "", regex=False).str.strip()
        df[c] = pd.to_numeric(s, errors="coerce").round().astype("Int64")
    return df


def add_county_rows(mvr: pd.DataFrame) -> pd.DataFrame:
    """County totals for the years whose sheets have none: the sum of each
    county's municipalities, for the whole-dollar lines only."""
    have = set(mvr.loc[mvr["Aggregation"] == "County", "Year"])
    missing = sorted(set(mvr["Year"]) - have)
    if not missing:
        return mvr
    base = mvr[~mvr["Aggregation"].isin(["County", "State"]) & mvr["Year"].isin(missing)]
    sums = (base.groupby(["Year", "County_ofMuni"], as_index=False)[WHOLE_DOLLARS]
                .sum(min_count=1))
    sums["Aggregation"] = "County"
    sums["Place"] = sums["County_ofMuni"].astype(str) + " COUNTY"
    print(f"  county rows added for {', '.join(map(str, missing))}")
    return pd.concat([mvr, sums.reindex(columns=mvr.columns)], ignore_index=True)


def build(path=paths.MVR_XLSX) -> pd.DataFrame:
    xls = pd.ExcelFile(path, engine="openpyxl")
    sheets = [s for s in xls.sheet_names if s.strip().isdigit() and int(s) >= FIRST_YEAR]
    mvr = pd.concat([read_year(xls, s) for s in sheets], ignore_index=True)
    mvr = mvr[["Year"] + BASE + list(LINES)]
    return add_county_rows(clean_types(mvr))


def main():
    mvr = build()
    mvr.to_csv(paths.MVR, index=False)
    n = mvr[mvr["Aggregation"] == "Muni"].groupby("Year").size()
    print(f"wrote {paths.MVR.relative_to(paths.ROOT)}: {len(mvr):,} rows, "
          f"years {n.index.min()}-{n.index.max()}, {n.iloc[-1]} municipalities in {n.index.max()}")


if __name__ == "__main__":
    main()
