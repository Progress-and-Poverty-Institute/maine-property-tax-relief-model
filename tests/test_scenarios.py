"""Properties every published scenario must have."""
import pytest


def by_group(committed, group):
    return [s for s in committed["scenarios"] if s["group"] == group]


def test_nineteen_scenarios(committed):
    # The nineteen published scenarios come first; any added in
    # model/local_scenarios.py follow, in their own group.
    ids = [s["id"] for s in committed["scenarios"]]
    assert ids[:19] == [str(i) for i in range(1, 20)]
    assert all(s["group"] == "local" for s in committed["scenarios"][19:])


def test_task_force_packages_redirect_what_they_spend(committed):
    # Money redirected is the Revenue Sharing I cut plus the reimbursement rate
    # saving, so it is at least the cut and, at 76%, exactly the cut.
    for s in by_group(committed, "october"):
        cut = float(s["parameter"].split("Rev I -$")[1].split("m")[0]) * 1e6
        assert s["redirected"] >= cut - 0.05e6, s["id"]
        if "reimbursement 76%" in s["parameter"]:
            assert s["redirected"] == pytest.approx(cut, abs=0.05e6), s["id"]


def test_cost35_scenarios_cost_the_state_35m(committed):
    for s in by_group(committed, "cost35"):
        assert s["state_cost"] == pytest.approx(35e6, abs=0.3e6), s["id"]


@pytest.mark.parametrize("group", ["realloc", "october"])
def test_funded_scenarios_cost_the_state_nothing_new(committed, group):
    # S14 (Homestead Plus) is the one exception: abolishing the exemption
    # frees more than its credit schedule spends.
    for s in by_group(committed, group):
        if s["id"] != "14":
            assert s["state_cost"] == pytest.approx(0.0, abs=0.1e6), s["id"]


def test_archetype_cells_add_to_scenario_totals(committed):
    for s in committed["scenarios"]:
        cells = sum(c["delivered"] for c in committed["broad_cells"] if c["s"] == s["id"])
        assert cells == pytest.approx(s["delivered"], abs=1.0), s["id"]


def test_one_mill_measure_for_every_scenario(committed):
    # Every scenario that moves a mill rate reports the levy-weighted average of
    # its towns' changes (bundle_geography.mill_summary), which must lie inside
    # the range of those changes. Credit-only scenarios move no rate.
    assert 10 < committed["average_mill"] < 20
    moves = set(committed["town_mill_scenarios"])
    for s in committed["scenarios"]:
        if s["id"] not in moves:
            assert s["mill_change"] == 0, s["id"]
            continue
        towns = [t["s" + s["id"]] for t in committed["towns"] if t["s" + s["id"]] is not None]
        assert min(towns) <= s["mill_change"] <= max(towns), s["id"]
        assert s["mill_change"] != 0, s["id"]


def test_expansion_split_covers_the_discretionary_spend(committed):
    for s in committed["scenarios"]:
        if s["id"] in ("9", "10", "11", "12", "13"):
            sp = s["expansion_split"]
            assert set(sp) == {"cap", "base", "offset"}, s["id"]
            assert sum(sp.values()) == pytest.approx(1.0, abs=1e-9), s["id"]
            assert all(0 < v < 1 for v in sp.values()), s["id"]
        else:
            assert s["expansion_split"] is None, s["id"]


def test_representative_archetypes_cover_every_household(committed):
    total = sum(a["households"] for a in committed["broad"])
    assert total == pytest.approx(committed["counts"]["households"], rel=1e-9)
