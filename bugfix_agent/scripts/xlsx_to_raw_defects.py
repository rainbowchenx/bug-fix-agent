#!/usr/bin/env python3
"""Convert a defect Excel export into raw-defects JSON for Agent-1.

薄壳：实现与 argparse 都在 :mod:`bugfix_agent.ingest.xlsx_source`，与
``csv_to_raw_defects.py`` 调用 ``load_platform_csv`` 的形状一致。

Usage:
  python3 xlsx_to_raw_defects.py --xlsx path.xlsx --product-line hc --out raw.json
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script from repo root / scripts dir.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bugfix_agent.ingest.xlsx_source import main  # noqa: E402

if __name__ == "__main__":
    main()
