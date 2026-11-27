"""
Save each run's raw data to disk, exactly as received.

Layout (one folder per run, never overwritten):

    data/raw/2026-09-28_0330Z/
        adzuna.jsonl.gz        one JSON posting per line, gzip-compressed
        ats.jsonl.gz
        manifest.json          what happened: counts, API calls, errors, timing

Why store RAW data instead of going straight into SQL tables?
Because our parsing rules WILL change (Phase 3: what counts as a "skill"?).
If we only kept parsed output, a better rule could never be applied to past
weeks. With the raw layer we can rebuild the SQL database from scratch at any
time. That's a standard data-engineering pattern: raw layer -> clean layer.
"""

import gzip
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def new_run_dir(run_id: str) -> Path:
    run_dir = DATA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)  # fail loudly rather than overwrite a run
    return run_dir


def write_records(run_dir: Path, name: str, records: list[dict]) -> Path:
    """JSON Lines = one JSON object per line: easy to stream, easy for pandas."""
    path = run_dir / f"{name}.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def write_manifest(run_dir: Path, manifest: dict) -> Path:
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return path


def read_records(path: Path) -> list[dict]:
    """Helper for later phases (and for eyeballing data in a notebook)."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]
