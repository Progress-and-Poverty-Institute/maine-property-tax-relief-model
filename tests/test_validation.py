"""The Technical Report's validation figures reproduce.

Every test here pins a figure printed in the Technical Report, computed from
the 2024 data shipped in this repository (tax year 2024 claimants, the 2024
MVR, MRS's fiscal notes). They are marked `report`: after the model is updated
with new data they are expected to fail, and can be skipped with
`python -m pytest tests -m "not report"`. See docs/updating.md.
"""
import pytest

from conftest import load_step

pytestmark = pytest.mark.report


def test_ptfc_validation_reproduces_report():
    v = load_step("07_validate").ptfc_validation()
    assert round(v["eligible"]) == 193_935
    assert round(v["claimants"]) == 134_245
    assert abs(v["delivered"] - 114_874_631) < 100      # report: $114.9 million
    assert abs(v["mrs_paid"] - 113_317_957) < 1         # report: $113.3 million


def test_homestead_check_reproduces_report():
    h = load_step("07_validate").homestead_check()
    assert abs(h["model"] - 84_571_330) < 100           # report: $84.6 million
    assert abs(h["mvr"] - 85_386_786) < 1               # report: $85.4 million


def test_fiscal_notes_reproduce_report():
    rows = load_step("07_validate").fiscal_notes()
    model = [r["model"] for r in rows]
    mrs = [r["mrs"] for r in rows]
    # LD 2212, prototypes of S1, S3, S5, S6: report's Category C
    for got, want in zip(model, [9_420_090, 35_226_178, 36_821_777, 32_658_691, 34_418_913]):
        assert abs(got - want) < 100
    for got, want in zip(mrs, [9_519_737, 34_358_600, 34_311_700, 29_427_743, 32_178_732]):
        assert abs(got - want) < 1
