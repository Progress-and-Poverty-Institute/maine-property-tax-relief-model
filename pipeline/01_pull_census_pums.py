#!/usr/bin/env python3
"""Pull the Maine ACS PUMS (2020-2024 5-year) from the Census API and build
one row per household with what the PTFC and homestead models need.

All person records are pulled, not just householders, so spouses and
dependents can be identified. Requires CENSUS_API_KEY, from the environment or
a .env file at the repository root. Raw API responses are cached in
data/derived/.pums_cache; the result is written to data/derived/pums_taxunits.csv.
"""
import json, os, sys, urllib.parse, urllib.request
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import paths  # noqa: E402

YEAR, STATE = 2024, "23"
DATASET = f"https://api.census.gov/data/{YEAR}/acs/acs5/pums"
CACHE = paths.PUMS_CACHE

# Variables are requested in blocks; each block's response is cached separately.
BLOCKS = {
    "p1": ["SERIALNO", "SPORDER", "RELSHIPP", "AGEP", "MAR", "PWGTP",
           "WGTP", "TEN", "HINCP", "TAXAMT", "VALP"],
    "p2": ["SERIALNO", "SPORDER", "NP", "TYPEHUGQ", "PUMA", "ADJINC",
           "ADJHSG", "GRNTP", "HHT", "MV"],
    "p3": ["SERIALNO", "SPORDER", "WAGP", "SEMP", "SSP", "RETP", "INTP",
           "PAP", "OIP", "SSIP"],
    # Contract rent.
    "p4": ["SERIALNO", "SPORDER", "RNTP"],
    # School enrolment, for the student limb of the dependent test.
    "p5": ["SERIALNO", "SPORDER", "SCH", "SCHG"],
}


def api_key():
    """CENSUS_API_KEY from the environment, the repo's .env, or ~/.census_api_key."""
    k = os.environ.get("CENSUS_API_KEY")
    if k:
        return k
    for f in [paths.ROOT / ".env", Path.home() / ".census_api_key"]:
        if f.exists():
            for line in f.read_text().splitlines():
                if line.strip().startswith("CENSUS_API_KEY"):
                    return line.split("=", 1)[1].strip().strip("\"' ")
    sys.exit("Set CENSUS_API_KEY. Free key: %s" % "https://api.census.gov/data/key_signup.html")


def fetch(tag, varlist, key):
    """One block of person records for Maine, from the cache or the API."""
    CACHE.mkdir(parents=True, exist_ok=True)
    local = CACHE / f"tu_{YEAR}_{tag}.json"
    if not local.exists():
        q = urllib.parse.urlencode({"get": ",".join(varlist),
                                    "for": f"state:{STATE}", "key": key})
        print(f"  GET {tag}: {len(varlist)} vars", file=sys.stderr)
        with urllib.request.urlopen(f"{DATASET}?{q}", timeout=1800) as r:
            body = r.read()
        if not body.lstrip().startswith(b"["):
            sys.exit(f"{tag}: {body[:300].decode(errors='replace')}")
        local.write_bytes(body)
    rows = json.loads(local.read_text())
    return pd.DataFrame(rows[1:], columns=rows[0])


def main():
    key = api_key()
    frames = [fetch(t, v, key) for t, v in BLOCKS.items()]
    df = frames[0]
    for f in frames[1:]:
        dup = [c for c in f.columns if c in df.columns
               and c not in ("SERIALNO", "SPORDER")]
        df = df.merge(f.drop(columns=dup), on=["SERIALNO", "SPORDER"],
                      how="inner")
    print(f"person rows: {len(df):,}", file=sys.stderr)

    num = [c for c in df.columns if c not in ("SERIALNO",)]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[df["TYPEHUGQ"] == 1]
    df = df[df["WGTP"] > 0]

    # ---- normalise the adjustment factors ----------------------------------
    # ADJINC and ADJHSG are published as integers scaled by 1,000,000.
    for c in ("ADJINC", "ADJHSG"):
        df[c] = df[c].where(df[c] < 100, df[c] / 1_000_000)

    hh = df[df["RELSHIPP"] == 20].copy()          # householder row
    hh = hh.rename(columns={"AGEP": "age_head", "MAR": "mar_head"})

    # spouse (21 = opposite-sex spouse, 23 = same-sex spouse)
    sp = (df[df["RELSHIPP"].isin([21, 23])]
          .groupby("SERIALNO")["AGEP"].max().rename("age_spouse"))

    # unmarried partner (22, 24) -- NOT a spouse for tax purposes; flagged only
    pt = (df[df["RELSHIPP"].isin([22, 24])]
          .groupby("SERIALNO").size().rename("n_partner"))

    # ---- not modelled: the veterans' doubling ---------------------------
    # 5219-KK(2-E) allows a resident individual who is a veteran and "100%
    # permanently and totally disabled" an ADDITIONAL credit equal to the
    # amount under 2-D, i.e. it doubles the PTFC, capped so the combined
    # credits cannot exceed property tax and rent constituting property tax
    # actually paid. The credit engine does not apply it, and this step does
    # not pull the disability rating. PUMS could not isolate the group anyway:
    # its DRAT code 5 puts "70, 80, 90, or 100 percent" in one bucket, misses
    # VA permanent-and-total status granted on individual unemployability at
    # a sub-100% schedular rating, and includes 100% ratings that are
    # temporary.

    # ---- dependents, per the statutory test -----------------------------
    # 36 M.R.S. sec 5219-KK sets the benefit base by the number of
    # "qualifying child or dependent" for whom the federal child tax credit
    # under IRC Section 24 can be claimed. Schedule PTFC routes this through
    # Form 1040ME line 13a: "each qualifying child and dependent of the
    # taxpayer for whom the federal child tax credit under Internal Revenue
    # Code, Section 24 was claimed for the same taxable year."
    #
    # Section 24 has two limbs: 24(a), a qualifying child under 17, and
    # 24(h), any OTHER Section 152 dependent, with no age limit. Because
    # line 13a says "and dependent", both count. So the relationship test is
    # Section 152(c)(2), which reaches siblings, grandchildren and foster
    # children as well as the householder's own children, and the age test
    # runs to 19, or to 24 for a student.
    #
    # NOT counted: Section 152(d) qualifying relatives, i.e. co-resident
    # parents and other adults. They are dependents in law, but Section 152
    # also requires the taxpayer to provide over half their support, and
    # that cannot be evaluated in PUMS. Nieces and nephews are likewise omitted:
    # they sit inside RELSHIPP 33 mixed with aunts and uncles, who are not
    # Section 152(c) relations. Both omissions bias n_dep DOWNWARD.
    QC_REL = [25, 26, 27,        # biological, adopted, step child
              28, 30, 35]        # sibling, grandchild, foster child
    student = df["SCH"].isin([2, 3])       # enrolled in the last 3 months
    qc = (df["RELSHIPP"].isin(QC_REL)
          & ((df["AGEP"] < 19) | ((df["AGEP"] < 24) & student)))
    kid = df[qc].groupby("SERIALNO").size().rename("n_dep")

    # ---- the youngest and oldest member ---------------------------------
    # Every person in the household, whatever their relationship. The credit
    # engine does not use these; they describe the sample (the Technical
    # Report's shares of households with someone under 18 and someone 65 or
    # over, printed by pipeline/09_report_figures.py).
    ages = df.groupby("SERIALNO")["AGEP"].agg(age_youngest="min", age_oldest="max")

    out = (hh.join(sp, on="SERIALNO").join(kid, on="SERIALNO")
             .join(pt, on="SERIALNO").join(ages, on="SERIALNO"))
    out["age_spouse"] = out["age_spouse"].fillna(-1)
    out["n_dep"] = out["n_dep"].fillna(0).astype(int)
    out["n_partner"] = out["n_partner"].fillna(0).astype(int)

    # ---- money, in constant dollars -------------------------------------
    out["income"] = out["HINCP"] * out["ADJINC"]
    out.loc[out["TAXAMT"] <= 0, "TAXAMT"] = 0.0     # -1 = N/A (non-owner)
    out.loc[out["VALP"] <= 0, "VALP"] = pd.NA
    out["prop_tax"] = out["TAXAMT"] * out["ADJHSG"]
    out["home_value"] = out["VALP"] * out["ADJHSG"]
    # Rent that counts toward the PTFC is CONTRACT rent (RNTP), not gross rent
    # (GRNTP = contract rent + utilities and fuels). MRS Rule 813 allows only rent
    # paid "solely for the right of occupancy" and excludes heat and utilities.
    # Gross rent is kept for reference.
    for c in ("GRNTP", "RNTP"):
        out[c] = out[c].fillna(0)
        out.loc[out[c] < 0, c] = 0
    out["rent_annual"] = out["RNTP"] * 12 * out["ADJHSG"]
    out["rent_gross_annual"] = out["GRNTP"] * 12 * out["ADJHSG"]

    out["owner"] = out["TEN"].isin([1, 2])
    out["renter"] = out["TEN"].isin([3, 4])
    out["married"] = out["age_spouse"] >= 0
    out["age_max"] = out[["age_head", "age_spouse"]].max(axis=1)
    out["senior"] = out["age_max"] >= 65

    keep = ["SERIALNO", "PUMA", "WGTP", "TEN", "owner", "renter", "HHT", "NP",
            "MV", "age_head", "age_spouse", "age_max", "age_youngest", "age_oldest",
            "senior", "mar_head",
            "married", "n_dep", "n_partner", "income", "prop_tax",
            "home_value", "rent_annual", "rent_gross_annual", "WAGP", "SEMP", "SSP", "RETP",
            "INTP", "PAP", "OIP", "SSIP"]
    res = out[keep]
    res.to_csv(paths.PUMS, index=False)
    print(f"households: {len(res):,}  weighted: {int(res['WGTP'].sum()):,}",
          file=sys.stderr)
    print(f"  owners {int(res.loc[res.owner,'WGTP'].sum()):,} | "
          f"renters {int(res.loc[res.renter,'WGTP'].sum()):,} | "
          f"married {int(res.loc[res.married,'WGTP'].sum()):,} | "
          f"with deps {int(res.loc[res.n_dep>0,'WGTP'].sum()):,}",
          file=sys.stderr)
    print(f"wrote {paths.PUMS}", file=sys.stderr)


if __name__ == "__main__":
    main()
