"""
Bundle every results/ file into ONE JSON file for the website.

    python site/build_data.py                  # -> site/data/data.json
    python site/build_data.py <output path>    # e.g. the public repo's docs/data/data.json

Only aggregated results (and the de-identified explorer table) go in,
never raw job data (DECISIONS.md, D15/D21).
"""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


def records(df: pd.DataFrame) -> list[dict]:
    # to_json turns NaN into null, which JavaScript understands
    return json.loads(df.to_json(orient="records"))


def build(out: Path) -> None:
    bundle = {
        "meta": json.loads((RESULTS / "meta.json").read_text()),
        "overview": json.loads((RESULTS / "overview.json").read_text()),
        "tables": {p.stem: records(pd.read_csv(p)) for p in sorted(RESULTS.glob("*.csv"))},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, separators=(",", ":"), ensure_ascii=False))
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, {len(bundle['tables'])} tables)")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site" / "data" / "data.json")
