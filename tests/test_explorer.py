"""The local Relief Explorer builds from any dashboard, including new scenarios."""
import json
import re

import pytest

import local_scenarios as LS
from conftest import ROOT, load_step


def _embedded(html, name):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % name, html, re.S)
    return json.loads(m.group(1))


def _sentences(obj):
    """Every sentence of written copy, tags removed."""
    if isinstance(obj, str):
        yield from re.split(r"(?<=[.!?])\s+", re.sub(r"<[^>]+>", "", obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _sentences(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _sentences(v)


def test_explorer_builds_with_every_scenario(tmp_path):
    out = load_step("08_build_explorer").build(out=tmp_path / "explorer.html")
    html = out.read_text(encoding="utf-8")
    dash = json.loads((ROOT / "output" / "dashboard.json").read_text(encoding="utf-8"))
    assert _embedded(html, "dashboard")["scenarios"] == dash["scenarios"]
    copy_x = _embedded(html, "copy_x")
    assert all(s["id"] in copy_x["scen"] for s in dash["scenarios"])
    assert "/maine-tax-relief-explorer/" not in html.split("<script")[0]   # nothing fetched from the site


def test_explorer_describes_a_scenario_it_has_no_text_for(tmp_path):
    dash = json.loads((ROOT / "output" / "dashboard.json").read_text(encoding="utf-8"))
    new = dict(dash["scenarios"][15], id="20", name="A test package", group="local",
               group_label=LS.GROUP_LABEL)
    dash["scenarios"].append(new)
    dash["groups"]["local"] = LS.GROUP_LABEL
    (tmp_path / "dashboard.json").write_text(json.dumps(dash), encoding="utf-8")
    html = load_step("08_build_explorer").build(tmp_path / "dashboard.json", tmp_path / "x.html") \
        .read_text(encoding="utf-8")
    s20 = _embedded(html, "copy_x")["scen"]["20"]
    assert s20["title"] == "A test package" and s20["redirected"] == new["redirected"]
    assert "Scenarios added locally" in html
    mill = load_step("08_build_explorer").mill_row(new["mill_change"], dash["average_mill"])
    assert ["Mill rates", "Average %.2f mills" % dash["average_mill"], mill] in s20["full"][-1]["rows"]


def test_explorer_tables_take_mill_figures_from_the_run(tmp_path):
    dash = json.loads((ROOT / "output" / "dashboard.json").read_text(encoding="utf-8"))
    for s in dash["scenarios"]:
        if s["id"] == "17":
            s["mill_change"] = 0.1234
    (tmp_path / "dashboard.json").write_text(json.dumps(dash), encoding="utf-8")
    html = load_step("08_build_explorer").build(tmp_path / "dashboard.json", tmp_path / "x.html") \
        .read_text(encoding="utf-8")
    rows = [r for b in _embedded(html, "copy_x")["scen"]["17"]["full"] if b.get("type") == "table"
            for r in b["rows"] if r[0] == "Mill rates"]
    assert rows == [["Mill rates", "Average %.2f mills" % dash["average_mill"],
                     "Increase of %.2f mills (+12.34%%)" % (0.1234 * dash["average_mill"])]]


@pytest.mark.report
def test_written_mill_figures_match_the_published_run():
    # Step 08 fills the tables from the run, but the prose is written by hand,
    # so every mill figure the Explorer's text quotes is checked here.
    dash = json.loads((ROOT / "output" / "dashboard.json").read_text(encoding="utf-8"))
    avg = "%.2f" % dash["average_mill"]
    site = ROOT / "explorer" / "data"
    copy = json.loads((site / "copy.json").read_text(encoding="utf-8"))
    copy_x = json.loads((site / "copy_x.json").read_text(encoding="utf-8"))
    wrong = []
    for s in dash["scenarios"]:
        if s["id"] not in copy_x["scen"] or s["mill_change"] == 0:
            continue
        mills = "%.2f" % abs(s["mill_change"] * dash["average_mill"])
        pct = "%.2f" % abs(100 * s["mill_change"])
        for sent in _sentences(copy_x["scen"][s["id"]]):
            if "mill" not in sent.lower():
                continue
            wrong += [(s["id"], sent) for v in re.findall(r"Average (\d+\.\d\d) mills", sent) if v != avg]
            wrong += [(s["id"], sent) for v in re.findall(r"(?<!Average )\b(\d+\.\d\d) mills", sent)
                      if v != mills]
            wrong += [(s["id"], sent) for v in re.findall(r"(\d+\.\d\d)%", sent) if v != pct]
    for sent in _sentences(copy["sections"]):
        wrong += [("about", sent) for v in re.findall(r"(\d+\.\d\d) mills", sent) if v != avg]
    change = {s["id"]: s["mill_change"] for s in dash["scenarios"]}
    for t in load_step("08_build_explorer")._tables(copy["sections"]):
        for row in t["rows"]:
            m = re.match(r"\s*(\d+)\.", re.sub(r"<[^>]+>", "", row[0]))
            for v in re.findall(r"mill rates (?:up|down) (\d+\.\d\d)%", " ".join(row[1:])):
                if not m or v != "%.2f" % abs(100 * change[m.group(1)]):
                    wrong.append(("summary", row[0]))
    assert not wrong, wrong


def test_local_scenarios_are_checked():
    ok = [LS.CreditChange("20", "x", {"cap_senior": 2_500.0}),
          LS.Package("21", "y", exemption=40_000.0, reimbursement=0.76)]
    assert LS.mill_ids(ok) == ["21"]
    for bad in ([LS.CreditChange("7", "x", {})],
                [LS.CreditChange("20", "x", {"cap_seniors": 1.0})],
                ok + [LS.CreditChange("21", "dup", {})],
                [LS.Package("22", "z", exemption=40_000.0, reimbursement=76)]):
        with pytest.raises(ValueError):
            LS.check(bad)
    assert LS.describe({"cap_senior": 2_500.0}, LS.E.TY2026) == \
        "maximum credit, 65 and over $2,500 (now $2,000)"
