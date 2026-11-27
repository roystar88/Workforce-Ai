"""
Weekly collection run. This is the script GitHub Actions calls every week.

Usage (from the project root, with the virtualenv active):

    python -m collector.run_collection            # full run: all sources
    python -m collector.run_collection --only ats # just company boards (no API key needed)
    python -m collector.run_collection --probe    # just print Adzuna match counts (~20 calls)
    python -m collector.run_collection --only adzuna_skills --backfill
                                                  # one-off: skill-tag ALL open DA postings (~90 calls)
    python -m collector.run_collection --only adzuna_skills --backfill --extra-titles
    python -m collector.run_collection --only adzuna_skills --backfill --extra-titles --titles "bi analyst,mis analyst"
                                                  # one-off: same for close analyst titles (~200 calls)

Design rule: one failing source must not lose the others' data. Each source
runs inside its own try/except, and its outcome is written to manifest.json.
The script exits with an error code if any source failed, which makes
GitHub Actions mark the run red and email you.
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from collector import adzuna, adzuna_skills, ats, config, storage
from collector.http_client import make_session

log = logging.getLogger("collector")

# Run in this order. adzuna_skills after adzuna: both use the same daily API quota.
SOURCES = {"adzuna": adzuna.collect, "adzuna_skills": adzuna_skills.collect, "ats": ats.collect}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect one weekly snapshot of job postings.")
    parser.add_argument("--only", choices=SOURCES, help="run a single source")
    parser.add_argument("--probe", action="store_true", help="print Adzuna match counts and exit")
    parser.add_argument("--backfill", action="store_true",
                        help="skill-tag every open posting, not just ones from the last 10 days")
    parser.add_argument("--extra-titles", action="store_true",
                        help="skill-tag the close analyst titles (SKILL_TAG_EXTRA_TITLES) instead of Data Analyst")
    parser.add_argument("--titles",
                        help="with --extra-titles: only these titles, comma-separated (to split a big run over two days)")
    parser.add_argument("--extra-tags", action="store_true",
                        help="tag EXTRA_TAGS (work mode, education, AI terms) instead of the 14 skills")
    args = parser.parse_args()
    if args.extra_tags:
        config.SKILLS = config.EXTRA_TAGS  # recorded in the manifest as skills_queried
    if args.backfill:
        config.SKILL_TAG_MAX_DAYS_OLD = None  # recorded in the manifest as max_days_old: null
    if args.extra_titles:
        config.SKILL_TAG_TITLES = config.SKILL_TAG_EXTRA_TITLES  # recorded as title_terms
        if args.titles:
            wanted = [t.strip() for t in args.titles.split(",") if t.strip()]
            unknown = [t for t in wanted if t not in config.SKILL_TAG_EXTRA_TITLES]
            if unknown:
                parser.error(f"not in SKILL_TAG_EXTRA_TITLES: {unknown}")
            config.SKILL_TAG_TITLES = wanted

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()  # reads .env locally; on GitHub the variables come from secrets
    session = make_session()

    if args.probe:
        for row in adzuna.probe(session):
            print(row)
        return 0

    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y-%m-%d_%H%MZ")  # e.g. 2026-09-28_0330Z (UTC)
    run_dir = storage.new_run_dir(run_id)
    log.info("run %s -> %s", run_id, run_dir)

    manifest = {"run_id": run_id, "started_at": started.isoformat(timespec="seconds"), "sources": {}}
    to_run = [args.only] if args.only else list(SOURCES)

    for name in to_run:
        t0 = time.monotonic()
        try:
            records, stats = SOURCES[name](session)
            path = storage.write_records(run_dir, name, records)
            manifest["sources"][name] = {"status": "ok", "file": path.name, "records": len(records), **stats}
            log.info("%s: saved %d records", name, len(records))
        except Exception as exc:
            log.exception("%s FAILED", name)
            manifest["sources"][name] = {"status": "failed", "error": str(exc)}
        manifest["sources"][name]["seconds"] = round(time.monotonic() - t0, 1)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    storage.write_manifest(run_dir, manifest)

    failed = [n for n, s in manifest["sources"].items() if s["status"] != "ok"]
    if failed:
        log.error("sources failed: %s (see %s/manifest.json)", failed, run_dir)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
