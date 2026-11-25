"""The committed outputs can be rebuilt from the committed inputs."""
import math

import numpy as np
import pandas as pd


import paths
from conftest import load_step

RTOL, ATOL = 1e-9, 1e-6

# No block needs a looser tolerance: the 6% line is compared after rounding
# (archetypes.above), so the S7 and S8 burden counts no longer depend on the
# computer. Add a block here, with a reason, only if one ever does.
PLATFORM_SENSITIVE = {}


def diff(a, b, path=""):
    """Yield (path, a, b) for every value that differs beyond tolerance."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k == "generated":
                continue
            if k not in a or k not in b:
                yield (f"{path}.{k}", a.get(k), b.get(k))
            else:
                yield from diff(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield (path, len(a), len(b))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                yield from diff(x, y, f"{path}[{i}]")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return
        if not math.isclose(a, b, rel_tol=RTOL, abs_tol=ATOL):
            yield (path, a, b)
    elif a != b:
        yield (path, a, b)


def test_dashboard_data_rebuilds(committed):
    fresh = load_step("06_build_dashboard_data").build()
    bad = []
    for p, a, b in diff(fresh, committed):
        block = p.split(".")[1].split("[")[0]
        tol = PLATFORM_SENSITIVE.get(block)
        if tol is not None and isinstance(a, float) and abs(a - b) <= tol:
            continue
        bad.append((p, a, b))
    assert not bad, bad[:20]


def test_reallocation_tables_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SCENARIO_DIR", tmp_path)
    load_step("04_reallocation_scenarios").main()
    for f in sorted(tmp_path.glob("*.csv")):
        pd.testing.assert_frame_equal(
            pd.read_csv(f), pd.read_csv(paths.DERIVED / "scenarios" / f.name),
            check_exact=False, rtol=1e-12)


def test_takeup_matches_the_state_totals():
    import ptfc_takeup as T
    t = T.takeup_by_puma()
    assert T.verify(t)["pass"].all()
    assert T.crosswalk_check(t)["pass"].all()
    committed = pd.read_csv(paths.TAKEUP_DIR / "ptfc_takeup_by_puma.csv", index_col=0)
    assert np.allclose(t["takeup_pct"].to_numpy(), committed["takeup_pct"].to_numpy())
