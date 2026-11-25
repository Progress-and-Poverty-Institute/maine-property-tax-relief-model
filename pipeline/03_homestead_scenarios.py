#!/usr/bin/env python3
"""Municipal mill rates under the three homestead exemption scenarios (S1-S3).

Solves each exemption so the State's net cost is $35 million and writes one
table per scenario to data/derived/scenarios/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import he_resolve_net as H  # noqa: E402

if __name__ == "__main__":
    H.main()
