#!/usr/bin/env python3
"""Build a local copy of the Relief Explorer from this run's output.

Writes output/explorer.html: the Maine Property Tax Relief Explorer
(https://landeconomics.org/maine-tax-relief-explorer) as one self-contained
file that opens in a browser with no internet connection, showing the results
in output/dashboard.json rather than the published ones.

The Explorer's own files are in explorer/ (see explorer/README.md): its page,
stylesheet and script, its images, and its written text (data/copy.json and
data/copy_x.json). This step puts them in one file with the dashboard data and
makes four changes on the way:

- Scenarios the written text does not cover, such as those added in
  model/local_scenarios.py, get a short description built from the scenario's
  name and parameters, so the Explorer can show them.
- The "Money redirected" figure for the Task Force scenarios and any local
  package is taken from this run (`redirected` in dashboard.json).
- The mill-rate figures in the scenario tables are taken from this run
  (`average_mill` and `mill_change` in dashboard.json): the "Mill rates" row of
  each scenario's table, and the mill change in the "What changes" column of
  the summary table.
- A banner says this is a local build: every chart and table shows this run,
  but the written text is from the published version.

The Explorer's script is used as published, apart from two lines that tell it
where to find its files (it would otherwise ask a web server for them).
"""
import base64
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import paths  # noqa: E402

SITE = paths.ROOT / "explorer"
OUT = paths.OUTPUT / "explorer.html"
PREFIX = "/maine-tax-relief-explorer/"

# The two lines of app.js that locate its files, and what replaces them.
APP_PATCHES = [
    ("const BASE = new URL('.', document.currentScript.src);",
     "const BASE = new URL('.', document.currentScript.src || location.href);"),
    ("const at = (p) => new URL(p, BASE).href;",
     "const at = (p) => (window.LOCAL_FILES && window.LOCAL_FILES[p]) || new URL(p, BASE).href;"),
]

# findings.csv is still requested by the script but no longer used by it.
FINDINGS_HEADER = ("scenario,scenario_name,set,archetype,archetype_name,basis,median_gain,"
                   "burden_now,burden_scen,share_better,rank_in_group,primary,extra_1,extra_2,"
                   "n_bullets\n")

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")

BANNER = """<div class="local-build" role="note" style="background:#fff4d6;border-bottom:1px solid #e2c46b;\
font-size:14px;line-height:1.45;padding:10px 0"><div class="wrap"><strong>Local build, {date}.</strong> \
This copy of the Relief Explorer shows the results of a model run on this computer, not the published \
version. Every chart and table is computed from this run; the written descriptions are from the \
published version and may not match it.{extra}</div></div>"""


def json_safe(x):
    """NaN and infinity as null, which is how a browser must receive them."""
    if isinstance(x, dict):
        return {k: json_safe(v) for k, v in x.items()}
    if isinstance(x, list):
        return [json_safe(v) for v in x]
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    return x


def data_uri(path: Path) -> str:
    kind = {".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg"}[path.suffix]
    return f"data:{kind};base64,{base64.b64encode(path.read_bytes()).decode()}"


def mill_row(change: float, average: float) -> str:
    """A scenario table's mill-rate cell, as the Explorer prints it."""
    if round(100 * change, 2) == 0:
        return "Unchanged"
    word, sign = ("Increase", "+") if change > 0 else ("Decrease", "−")
    return f"{word} of {abs(change) * average:.2f} mills ({sign}{abs(100 * change):.2f}%)"


def _tables(obj):
    """Every table block anywhere inside a piece of copy."""
    if isinstance(obj, dict):
        if obj.get("type") == "table":
            yield obj
        for v in obj.values():
            yield from _tables(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _tables(v)


def fill_mill_figures(dash: dict, copy: dict, copy_x: dict) -> int:
    """Put this run's mill-rate figures into the written copy's tables.

    Returns the number of cells filled. The prose is not changed: it is checked
    against the published run by tests/test_explorer.py instead.
    """
    avg = dash["average_mill"]
    change = {s["id"]: s["mill_change"] for s in dash["scenarios"]}
    n = 0
    for sid, sc in copy_x["scen"].items():
        for t in _tables(sc):
            for row in t["rows"]:
                if re.sub(r"<[^>]+>", "", row[0]).strip() == "Mill rates" and sid in change:
                    row[1] = f"Average {avg:.2f} mills"
                    row[2] = mill_row(change[sid], avg)
                    n += 1
    for t in _tables(copy["sections"]):
        for row in t["rows"]:
            m = re.match(r"\s*(\d+)\.", re.sub(r"<[^>]+>", "", row[0]))
            if not m or m.group(1) not in change or len(row) < 3:
                continue
            c = change[m.group(1)]
            new = re.sub(r"mill rates (up|down) \d+\.\d\d%",
                         f"mill rates {'up' if c > 0 else 'down'} {abs(100 * c):.2f}%", row[2])
            n += new != row[2]
            row[2] = new
    return n


def placeholder_copy(dash: dict, copy_x: dict) -> list:
    """Written copy for every scenario the Explorer text does not cover."""
    added = []
    for s in dash["scenarios"]:
        if s["id"] in copy_x["scen"]:
            continue
        local = s["group"] == "local"
        intro = (f"Scenario {s['id']} was added for this run"
                 + (" in <code>model/local_scenarios.py</code>" if local else "")
                 + ". It has no written description: the figures and charts on this page are "
                   "computed from the model run.")
        params = f"<strong>What it changes:</strong> {s['parameter']}."
        full = [dict(type="p", html=intro), dict(type="p", html=params)]
        if round(100 * s["mill_change"], 2) != 0:
            full.append(dict(type="table", head=["Parameter", "Current", f"Under Scenario {s['id']}"],
                             rows=[["Mill rates", "", ""]]))
        copy_x["scen"][s["id"]] = dict(
            title=s["name"],
            full=full,
            short=[dict(type="p", html=params)],
            row=dict(programme="Added locally" if local else s["group_label"],
                     changes=s["parameter"]))
        added.append(s["id"])
    return added


def build(dash_path=paths.DASHBOARD_JSON, out=OUT) -> Path:
    dash = json_safe(json.loads(Path(dash_path).read_text(encoding="utf-8")))
    copy = json.loads((SITE / "data" / "copy.json").read_text(encoding="utf-8"))
    copy_x = json.loads((SITE / "data" / "copy_x.json").read_text(encoding="utf-8"))

    added = placeholder_copy(dash, copy_x)
    fill_mill_figures(dash, copy, copy_x)
    for s in dash["scenarios"]:
        if s.get("redirected") is not None and s["group"] != "realloc":
            copy_x["scen"][s["id"]]["redirected"] = s["redirected"]

    app = (SITE / "app.js").read_text(encoding="utf-8")
    for old, new in APP_PATCHES:
        if app.count(old) != 1:
            raise SystemExit(f"explorer/app.js has changed: cannot find the line\n  {old}\n"
                             "Update APP_PATCHES in pipeline/08_build_explorer.py.")
        app = app.replace(old, new)
    if "</script" in app.lower():
        raise SystemExit("explorer/app.js contains '</script', which cannot be inlined")

    def embed(obj_or_text):
        text = (obj_or_text if isinstance(obj_or_text, str)
                else json.dumps(obj_or_text, ensure_ascii=False, allow_nan=False))
        return text.replace("</", "<\\/")

    files = {"data/dashboard.json": "local:dashboard", "data/copy.json": "local:copy",
             "data/copy_x.json": "local:copy_x", "data/findings.csv": "local:findings"}
    for a in sorted((SITE / "assets").iterdir()):
        files[f"assets/{a.name}"] = data_uri(a)
    shim = """
window.LOCAL_FILES = %s;
(function () {
  var real = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (url, opts) {
    var u = String(url);
    if (u.indexOf('local:') === 0) {
      var el = document.getElementById(u.slice(6));
      return Promise.resolve(new Response(el.textContent, {status: 200}));
    }
    return real(url, opts);
  };
})();
""" % json.dumps(files)

    html = (SITE / "index.html").read_text(encoding="utf-8")
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    script_tag = f'<script src="{PREFIX}app.js"></script>'
    swaps = [
        (f'<link rel="stylesheet" href="{PREFIX}styles.css">', f"<style>\n{css}\n</style>"),
        ("<title>Maine Property Tax Relief Explorer</title>",
         "<title>Maine Property Tax Relief Explorer (local build)</title>"),
        ('<div class="tabs-bar">',
         BANNER.format(date=f"{int(dash['generated'][8:10])} "
                            f"{MONTHS[int(dash['generated'][5:7]) - 1]} {dash['generated'][:4]}",
                       extra=(" Scenarios added locally are in their own group, "
                              "&ldquo;Scenarios added locally&rdquo;."
                              if any(s["group"] == "local" for s in dash["scenarios"]) else ""))
         + '\n<div class="tabs-bar">'),
        (script_tag, "<!--app-->"),
    ]
    for old, new in swaps:
        if html.count(old) != 1:
            raise SystemExit(f"explorer/index.html has changed: cannot find\n  {old}")
        html = html.replace(old, new)
    for a in sorted((SITE / "assets").iterdir()):
        html = html.replace(f'src="{PREFIX}assets/{a.name}"', f'src="{data_uri(a)}"')
    if PREFIX in html:
        i = html.index(PREFIX)
        raise SystemExit(f"explorer/index.html refers to a file this step does not inline: {html[i - 40:i + 60]}")
    html = html.replace("<!--app-->",
                        '<script type="application/json" id="dashboard">%s</script>\n'
                        '<script type="application/json" id="copy">%s</script>\n'
                        '<script type="application/json" id="copy_x">%s</script>\n'
                        '<script type="text/plain" id="findings">%s</script>\n'
                        '<script>%s</script>\n<script>\n%s\n</script>'
                        % (embed(dash), embed(copy), embed(copy_x), FINDINGS_HEADER, shim, app))

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB): {len(dash['scenarios'])} scenarios"
          + (f"; written description generated for {', '.join('S' + a for a in added)}" if added else ""))
    return out


if __name__ == "__main__":
    build()
