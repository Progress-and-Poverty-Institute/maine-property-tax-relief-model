#!/usr/bin/env python3
"""What the State's relief programmes cost and deliver under current law.

Writes data/derived/baseline_totals.csv.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import baseline_programs as BP  # noqa: E402
import paths                    # noqa: E402

if __name__ == "__main__":
    t = BP.Baseline().totals()
    t.to_csv(paths.BASELINE_TOTALS, index=False)
    print(t.round(1).to_string(index=False))
