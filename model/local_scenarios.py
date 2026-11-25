"""Scenarios of your own, added to the dashboard and the local Explorer.

Every scenario listed in SCENARIOS below is built by `make` alongside the
nineteen published ones, in a fourth group, "Scenarios added locally", and
appears in output/dashboard.json and output/explorer.html. As shipped the list
is empty, so the published outputs are unchanged. See docs/new-policy.md.

Two kinds, the same two as the worked examples in docs/new-policy.md:

    CreditChange(id, name, changes)
        A change to the Fairness Credit alone, every other program as today.
        `changes` maps fields of ptfc_engine.Params to new values, for example
        {"cap_senior": 2_500.0}. The State's cost is whatever the change costs.

    Package(id, name, exemption, reimbursement, credit={}, revi_cut=None)
        A homestead exemption and reimbursement rate, with any Fairness Credit
        changes in `credit` (Params fields, as above), paid for by cutting
        Revenue Sharing I, as in Scenarios 15 to 19. With revi_cut=None the cut
        is solved so the State's net cost is zero; give a dollar figure to fix
        it instead.

Ids are whole numbers above 19, as text ("20", "21", ...).

The Params fields: base_single, base_hoh_one, base_joint_multi, base_senior (the
four benefit bases), cap_under65, cap_senior (the two maximum credits),
rate_income (the income threshold, 0.04) and rate_rent (the share of rent
counted as property tax, 0.15). Current law is ptfc_recalibrate.baseline_params().
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

import ptfc_engine as E

GROUP = "local"
GROUP_LABEL = "Scenarios added locally"


@dataclass(frozen=True)
class CreditChange:
    id: str
    name: str
    changes: dict


@dataclass(frozen=True)
class Package:
    id: str
    name: str
    exemption: float
    reimbursement: float
    credit: dict = field(default_factory=dict)
    revi_cut: float | None = None


SCENARIOS = [
    # Examples (remove the # to use them):
    # CreditChange("20", "Raise the 65+ maximum credit to $2,500", {"cap_senior": 2_500.0}),
    # Package("21", "Exemption $40,000 at 76%, maximum credits $2,250 and $3,000",
    #         exemption=40_000.0, reimbursement=0.76,
    #         credit={"cap_under65": 2_250.0, "cap_senior": 3_000.0}),
]

_PARAMS = {f.name for f in fields(E.Params)}
LABELS = {
    "base_single": "benefit base, single",
    "base_hoh_one": "benefit base, couple or single parent with one dependent",
    "base_joint_multi": "benefit base, with dependents",
    "base_senior": "benefit base, 65 and over",
    "cap_under65": "maximum credit, under 65",
    "cap_senior": "maximum credit, 65 and over",
    "rate_income": "income threshold",
    "rate_rent": "share of rent counted",
}


def describe(changes: dict, p0) -> str:
    """The credit changes in words, e.g. 'maximum credit, 65 and over $2,500 (now $2,000)'."""
    def val(f, v):
        return f"{100 * v:.2f}%" if f.startswith("rate_") else f"${v:,.0f}"
    return "; ".join(f"{LABELS[f]} {val(f, v)} (now {val(f, getattr(p0, f))})"
                     for f, v in changes.items()) or "Fairness Credit unchanged"


def check(scenarios=None) -> list:
    """The registered scenarios, after checking ids and parameter names."""
    scenarios = SCENARIOS if scenarios is None else scenarios
    seen = set()
    for s in scenarios:
        if not (s.id.isdigit() and int(s.id) > 19):
            raise ValueError(f"local scenario id {s.id!r}: use a whole number above 19, as text")
        if s.id in seen:
            raise ValueError(f"local scenario id {s.id!r} is used twice")
        seen.add(s.id)
        bad = set(s.changes if isinstance(s, CreditChange) else s.credit) - _PARAMS
        if bad:
            raise ValueError(f"local scenario {s.id}: not Fairness Credit parameters: {sorted(bad)}")
        if isinstance(s, Package) and not 0.0 <= s.reimbursement <= 1.0:
            raise ValueError(f"local scenario {s.id}: reimbursement is a share, 0 to 1")
    return list(scenarios)


def mill_ids(scenarios=None) -> list:
    """Ids of the local scenarios that move mill rates (the packages)."""
    return [s.id for s in check(scenarios) if isinstance(s, Package)]
