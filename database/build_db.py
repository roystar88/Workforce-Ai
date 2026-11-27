"""
Build (or rebuild) the SQLite database from every raw weekly snapshot.

Usage (from the project root, with the virtualenv active):

    python -m database.build_db

What it does:
  1. Deletes data/workforce.db and recreates the tables from schema.sql.
  2. Walks through data/raw/<run_id>/ folders in date order.
  3. For each posting, turns the source's JSON into one `postings` row
     (each source names its fields differently: see the _from_* functions)
     and records a `sightings` row: "this posting was open in this run".

Why rebuild from scratch every time instead of adding only the new week?
Because it's simple and always correct: if we fix a mapping bug below, one
rerun re-applies the fix to every past week. With ~6,000 postings a week this
takes seconds. (See DECISIONS.md, D4.)
"""

import html
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from collector.storage import DATA_DIR, read_records

DB_PATH = DATA_DIR.parent / "workforce.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# The postings columns, in the order our row dicts use them.
POSTING_COLUMNS = [
    "posting_id", "source", "title", "company_name", "location_text", "region",
    "city", "created_at", "salary_min", "salary_max", "salary_is_predicted",
    "description", "description_is_full", "category", "contract_time", "url",
]


# --- One translator per source: raw JSON record -> postings row (a dict) ----

def _from_adzuna(rec: dict) -> dict:
    p = rec["payload"]
    # Adzuna's location.area goes from broad to narrow:
    # ["India", "Karnataka", "Bangalore", ...]
    area = (p.get("location") or {}).get("area") or []
    has_salary = p.get("salary_min") is not None or p.get("salary_max") is not None
    return {
        "title": p.get("title"),
        "company_name": (p.get("company") or {}).get("display_name"),
        "location_text": (p.get("location") or {}).get("display_name"),
        "region": area[1] if len(area) > 1 else None,
        "city": area[2] if len(area) > 2 else None,
        "created_at": p.get("created"),
        "salary_min": p.get("salary_min"),
        "salary_max": p.get("salary_max"),
        # Only meaningful when there IS a salary; otherwise NULL.
        "salary_is_predicted": int(p["salary_is_predicted"]) if has_salary else None,
        "description": p.get("description"),
        "description_is_full": 0,  # Adzuna cuts descriptions at 500 characters
        "category": (p.get("category") or {}).get("label"),
        "contract_time": p.get("contract_time"),
        "url": p.get("redirect_url"),
    }


def _from_greenhouse(rec: dict) -> dict:
    p = rec["payload"]
    return {
        "title": p.get("title"),
        "company_name": p.get("company_name") or rec["company_slug"],
        "location_text": (p.get("location") or {}).get("name"),
        "created_at": p.get("first_published") or p.get("updated_at"),
        # Greenhouse double-encodes its HTML ("&lt;p&gt;"). unescape -> "<p>".
        # Stripping the HTML tags themselves is a Phase 3 (cleaning) job.
        "description": html.unescape(p.get("content") or ""),
        "description_is_full": 1,
        "url": p.get("absolute_url"),
    }


def _from_lever(rec: dict) -> dict:
    p = rec["payload"]
    # Lever splits the description into parts; the "lists" part usually holds
    # the requirements (i.e. the skills!), so we glue all parts together.
    parts = [p.get("descriptionPlain") or ""]
    for lst in p.get("lists") or []:
        parts.append(lst.get("text", ""))
        parts.append(lst.get("content", ""))  # HTML <li> items
    parts.append(p.get("additionalPlain") or "")
    created_ms = p.get("createdAt")  # Lever uses milliseconds since 1970
    return {
        "title": p.get("text"),
        "company_name": rec["company_slug"],
        "location_text": (p.get("categories") or {}).get("location"),
        "created_at": (datetime.fromtimestamp(created_ms / 1000, timezone.utc).isoformat()
                       if created_ms else None),
        "description": "\n".join(x for x in parts if x),
        "description_is_full": 1,
        "url": p.get("hostedUrl"),
    }


def _from_ashby(rec: dict) -> dict:
    p = rec["payload"]
    return {
        "title": p.get("title"),
        "company_name": rec["company_slug"],
        "location_text": p.get("location"),
        "created_at": p.get("publishedAt"),
        "description": p.get("descriptionPlain"),
        "description_is_full": 1,
        "url": p.get("jobUrl"),
    }


TRANSLATORS = {
    "adzuna": _from_adzuna,
    "greenhouse": _from_greenhouse,
    "lever": _from_lever,
    "ashby": _from_ashby,
}


def _to_row(rec: dict) -> tuple:
    row = dict.fromkeys(POSTING_COLUMNS)  # every column starts as NULL...
    row.update(TRANSLATORS[rec["source"]](rec))  # ...then the source fills what it has
    row["posting_id"] = f"{rec['source']}:{rec['source_job_id']}"
    row["source"] = rec["source"]
    return tuple(row[c] for c in POSTING_COLUMNS)


# --- The build itself --------------------------------------------------------

# "UPSERT" = insert the row, or UPDATE it if that posting_id already exists.
# Runs are processed oldest -> newest, so the latest version of a posting wins.
UPSERT_POSTING = f"""
    INSERT INTO postings ({", ".join(POSTING_COLUMNS)})
    VALUES ({", ".join("?" for _ in POSTING_COLUMNS)})
    ON CONFLICT(posting_id) DO UPDATE SET
    {", ".join(f"{c} = excluded.{c}" for c in POSTING_COLUMNS if c != "posting_id")}
"""
# The ? marks are placeholders: sqlite3 fills them in safely from our tuples.
# Never build SQL by pasting values into the string yourself: a title
# containing a quote (e.g. "Analyst's role") would break the query.


def build() -> None:
    DB_PATH.unlink(missing_ok=True)  # start fresh
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA_PATH.read_text())

    run_dirs = sorted(d for d in DATA_DIR.iterdir() if (d / "manifest.json").exists())
    for run_dir in run_dirs:
        manifest = json.loads((run_dir / "manifest.json").read_text())
        started = datetime.fromisoformat(manifest["started_at"])
        iso_year, iso_week, _ = started.isocalendar()
        sources = manifest["sources"]
        con.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
            (manifest["run_id"], manifest["started_at"], f"{iso_year}-W{iso_week:02d}",
             sources.get("adzuna", {}).get("records"), sources.get("ats", {}).get("records")),
        )

        tag_stats = sources.get("adzuna_skills", {})
        if tag_stats.get("status") == "ok":
            # Older manifests stored a single "title_term"; newer ones a list.
            titles = tag_stats.get("title_terms") or [tag_stats["title_term"]]
            con.executemany(
                "INSERT INTO skill_tag_runs VALUES (?, ?, ?, ?, ?)",
                [(manifest["run_id"], manifest["started_at"], title,
                  tag_stats["max_days_old"], json.dumps(tag_stats["skills_queried"]))
                 for title in titles],
            )

        for file in sorted(run_dir.glob("*.jsonl.gz")):
            records = read_records(file)
            if file.name == "adzuna_skills.jsonl.gz":
                # Skill tags aren't postings: they go to their own table.
                con.executemany(
                    "INSERT OR IGNORE INTO posting_skills VALUES (?, ?)",
                    [(f"adzuna:{r['source_job_id']}", r["skill"]) for r in records],
                )
                continue
            con.executemany(UPSERT_POSTING, [_to_row(r) for r in records])
            con.executemany(
                "INSERT INTO sightings VALUES (?, ?)",
                [(manifest["run_id"], f"{r['source']}:{r['source_job_id']}") for r in records],
            )
            con.executemany(
                "INSERT OR IGNORE INTO posting_search_terms VALUES (?, ?)",
                [(f"{r['source']}:{r['source_job_id']}", term)
                 for r in records for term in r.get("search_terms", [])],
            )
        print(f"loaded {manifest['run_id']}")

    con.commit()  # nothing is saved to disk until commit
    for table in ("runs", "postings", "sightings", "posting_search_terms",
                  "posting_skills", "skill_tag_runs", "skill_tagged_postings"):
        print(f"{table:22s} {con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:>7,} rows")
    con.close()
    print(f"database written to {DB_PATH}")


if __name__ == "__main__":
    build()
