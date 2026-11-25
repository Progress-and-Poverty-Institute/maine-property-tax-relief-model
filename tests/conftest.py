import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))


def load_step(name):
    """Import a pipeline script (its file name starts with a digit)."""
    path = ROOT / "pipeline" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name.split("_", 1)[1], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "report: checks a figure in the Technical Report, computed from the 2024 data "
        "shipped here. Expected to fail after the data are updated; skip these with "
        "`python -m pytest tests -m \"not report\"` (see docs/updating.md).")


@pytest.fixture(scope="session")
def committed():
    return json.loads((ROOT / "output" / "dashboard.json").read_text())
