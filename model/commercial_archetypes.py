"""The six commercial archetypes, and what each pays under every scenario.

These are the only figures on the dashboard that the model does not compute. A
named parcel's bill is read from its municipal commitment book, not derived as
a mill rate times an assessment.

The model's mill rates, from the 2024 Municipal Valuation Return, differ from
two of the commitment books:

    town      model   book
    Bangor    18.55   17.70
    Camden    10.50   11.50
    Gardiner  25.60   25.60
    Raymond   17.20   17.20
    York       8.40    8.40

Bangor's and Camden's rates and bills are from their fiscal year 2026 tax
commitment books, a later year than the 2024 MVR (the rates are within 10% of
the 2024 rates: 4.6% lower in Bangor, 9.5% higher in Camden). The model's
percentage CHANGES therefore apply to these parcels, but the bill LEVEL comes
from the book.

Scenarios 4 to 8 move no mill rate, so every commercial bill is unchanged under
them: the Fairness Credit is a State payment to households and never touches a
municipal levy.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import bundle_geography as G
import bundle_scenarios as B
import ptfc_takeup as T


@dataclass(frozen=True)
class Parcel:
    id: str
    label: str
    town: str          # commitment-book spelling, before T._key
    assessed: float
    billed: float      # ANNUAL, from the municipal commitment book
    units: int         # dwelling units; 1 for a single commercial tenant
    source: str

    @property
    def per_unit(self) -> float:
        return self.billed / self.units


#  `billed` is the figure the town's own commitment book shows, except where
#  `source` says "not a single parcel": there the bill is the archetype median
#  assessment times the town's 2024 MVR rate (Gardiner: $275,000 x 25.60 mills).
ARCHETYPES = (
    Parcel("C1", "A martial arts studio in Bangor", "Bangor",
           496_500.0, 8_788.05, 1, "Bangor commitment book"),
    Parcel("C2", "A repair shop in Gardiner", "Gardiner",
           275_000.0, 7_040.00, 1, "archetype median x 2024 MVR rate; not a single parcel"),
    Parcel("C3", "A restaurant in Camden", "Camden",
           843_478.0, 9_700.00, 1, "Camden commitment book"),
    Parcel("C4", "A law firm in Raymond", "Raymond",
           310_500.0, 5_340.60, 1, "Raymond commitment book"),
    Parcel("C5", "A lumber yard in York", "York",
           1_183_400.0, 9_940.00, 1, "York commitment book (two half-year instalments)"),
    Parcel("C6", "An apartment complex in Bangor", "Bangor",
           1_258_700.0, 22_278.99, 10, "Bangor commitment book; 10 units on 3 cards"),
)


def mill_pct() -> dict:
    """{town key: {scenario id: fractional mill change}}. 4-8 are absent = no change."""
    out = {}
    for r in G.town_rows():
        out[r["town"]] = {s: r.get("s" + s) for s in G.MILL_SCENARIOS}
    return out


def table() -> list:
    """One row per archetype per scenario: the bill, the change, and per unit."""
    pct, rows = mill_pct(), []
    for p in ARCHETYPES:
        key = T._key(pd.Series([p.town]))[0]
        tp = pct.get(key, {})
        for sid in B.ORDER:
            f = tp.get(sid) or 0.0
            d = p.billed * f
            rows.append(dict(a=p.id, s=sid, town=p.town, units=p.units,
                             bill_base=round(p.billed, 2),
                             bill_scen=round(p.billed + d, 2),
                             change=round(d, 2),
                             change_per_unit=round(d / p.units, 2),
                             mill_pct=round(100 * f, 4)))
    return rows


def rows() -> list:
    """The archetypes themselves, for the dashboard."""
    return [dict(id=p.id, label=p.label, town=p.town, assessed=p.assessed,
                 billed=round(p.billed, 2), units=p.units,
                 billed_per_unit=round(p.per_unit, 2))
            for p in ARCHETYPES]

