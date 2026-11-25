"""The steps that let the model take new data reproduce the shipped inputs.

Each test checks that a figure the model once had typed in now comes out of
the source file. Tests marked `report` also check that it comes out at the
value the Technical Report uses, so they are expected to fail after the data
are updated (see docs/updating.md); the others hold for any data.
"""
import io
import json

import numpy as np
import pytest

from conftest import ROOT, load_step


def test_mvr_preparation_reproduces_shipped_csv():
    # Compared as values, to floating-point precision, not as text: pandas
    # versions differ in the last digit they read for a few workbook cells
    # (0.24133000000000004 is read as 0.24133 by pandas 3.0, exactly by 3.1).
    import pandas as pd
    import paths
    built = load_step("00_prepare_mvr").build()
    buf = io.StringIO()
    built.to_csv(buf, index=False)
    buf.seek(0)
    pd.testing.assert_frame_equal(pd.read_csv(buf, low_memory=False),
                                  pd.read_csv(paths.MVR, low_memory=False),
                                  check_exact=False, rtol=1e-12)


@pytest.mark.report
def test_revenue_sharing_totals_from_projections():
    import fund_totals as F
    rs = F.revenue_sharing()
    assert rs["rev_i"] == 208_500_000          # report: $208.5 million
    assert rs["rev_ii"] == 56_100_000          # report: $56.1 million


@pytest.mark.report
def test_reallocation_pools():
    import reallocation as RA
    want = {"9": 208.5e6, "10": 56.1e6, "11": 28.5e6, "12": 85.4e6, "13": 350.0e6}
    assert {s: RA.gross_pool(s) for s in want} == want


@pytest.mark.report
def test_ptfc_totals_from_mrs_file():
    import ptfc_takeup as T
    assert T.mrs_file_totals() == dict(claimants=134_245, credit=113_317_957)


def test_home_value_counts_round_trip(tmp_path):
    """Homes placed at the shipped counts give the shipped counts back."""
    import he_resolve_net as H
    shipped = json.loads((ROOT / "data" / "derived" / "home_value_counts.json").read_text())
    values = np.concatenate([np.repeat(H._CAP_MIDS, H._CAP_COUNTS),
                             np.full(H._CAP_TAIL, 150_000.0),
                             np.full(500, 10_000.0)])          # below $25,000: left out
    got = H.value_cap_counts(values)
    assert got["counts"] == shipped["counts"]
    assert got["at_or_above_100000"] == shipped["at_or_above_100000"]
    assert got["n"] == sum(shipped["counts"]) + shipped["at_or_above_100000"]
    # Weights: every home counted twice doubles every count.
    assert H.value_cap_counts(values, np.full(len(values), 2.0))["n"] == 2 * got["n"]

    # The command-line tool writes the same counts.
    csv = tmp_path / "homes.csv"
    csv.write_text("v\n" + "\n".join(map(str, values)))
    out = tmp_path / "counts.json"
    load_tool = __import__("importlib.util").util
    spec = load_tool.spec_from_file_location("hvc", ROOT / "tools" / "home_value_counts.py")
    mod = load_tool.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main([str(csv), "--value-column", "v", "--out", str(out)])
    assert json.loads(out.read_text())["counts"] == shipped["counts"]
