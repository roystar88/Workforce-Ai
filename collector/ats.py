"""
Fetch job postings from company job boards (Greenhouse, Lever, Ashby).

"ATS" = Applicant Tracking System: the software companies use to post jobs
and manage applicants. Greenhouse, Lever and Ashby each expose a PUBLIC,
no-login JSON API that the companies' own careers pages are built from.
Unlike Adzuna, these give us the FULL job description, which matters a lot
for extracting skills in Phase 3.

Each ATS returns a differently-shaped JSON, so each has a small adapter that
answers the same two questions: "where is this job?" and "what's its title?".
The raw record is stored untouched either way.
"""

import logging
import re
from datetime import datetime, timezone

from collector import config

log = logging.getLogger(__name__)

# Build the filters once from the keyword lists in config.py.
# \b = word boundary, so "bi" matches "BI Analyst" but not "mobile".
_INDIA_RE = re.compile("|".join(config.INDIA_LOCATION_KEYWORDS), re.IGNORECASE)
_TITLE_RE = re.compile(r"\b(" + "|".join(config.ATS_TITLE_KEYWORDS) + r")\b", re.IGNORECASE)


# --- One adapter per ATS: (url, list-of-jobs extractor, title, location text)

def _greenhouse_url(slug):
    # content=true => include the full description HTML
    return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

def _greenhouse_jobs(data):
    return data.get("jobs", [])

def _greenhouse_where(job):
    offices = " ".join(o.get("location") or o.get("name", "") for o in job.get("offices", []))
    return f"{(job.get('location') or {}).get('name', '')} {offices}"


def _lever_url(slug):
    return f"https://api.lever.co/v0/postings/{slug}?mode=json"

def _lever_jobs(data):
    return data if isinstance(data, list) else []

def _lever_where(job):
    cats = job.get("categories") or {}
    all_locs = " ".join(cats.get("allLocations") or [])
    # Lever gives a 2-letter country code; turn "IN" into a matchable word.
    country = "india" if job.get("country") == "IN" else ""
    return f"{cats.get('location', '')} {all_locs} {country}"


def _ashby_url(slug):
    return f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

def _ashby_jobs(data):
    return data.get("jobs", [])

def _ashby_where(job):
    secondary = " ".join(s.get("location", "") for s in job.get("secondaryLocations") or [])
    country = ((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
    return f"{job.get('location', '')} {secondary} {country}"


ADAPTERS = {
    #  name         boards list               url              jobs          title key  location
    "greenhouse": (config.GREENHOUSE_BOARDS, _greenhouse_url, _greenhouse_jobs, "title", _greenhouse_where),
    "lever":      (config.LEVER_BOARDS,      _lever_url,      _lever_jobs,      "text",  _lever_where),
    "ashby":      (config.ASHBY_BOARDS,      _ashby_url,      _ashby_jobs,      "title", _ashby_where),
}


def collect(session) -> tuple[list[dict], dict]:
    """Fetch every configured board; keep India-based, analyst-adjacent jobs."""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records, per_board, failed = [], {}, []

    for ats_name, (slugs, url_fn, jobs_fn, title_key, where_fn) in ADAPTERS.items():
        for slug in slugs:
            board = f"{ats_name}/{slug}"
            try:
                resp = session.get(url_fn(slug), timeout=30)
                resp.raise_for_status()  # safe here: these URLs contain no secrets
                jobs = jobs_fn(resp.json())
            except Exception as exc:
                # One broken board (renamed, removed) must not kill the whole run.
                log.warning("%s failed: %s", board, exc)
                failed.append(board)
                continue

            india = [j for j in jobs if _INDIA_RE.search(where_fn(j))]
            kept = [j for j in india if _TITLE_RE.search(j.get(title_key, ""))]
            for job in kept:
                records.append({
                    "source": ats_name,
                    "source_job_id": f"{slug}:{job['id']}",  # ids are only unique per board
                    "company_slug": slug,
                    "fetched_at": fetched_at,
                    "payload": job,
                })
            per_board[board] = {"total": len(jobs), "india": len(india), "kept": len(kept)}
            log.info("%-45s total=%-4d india=%-4d kept=%d", board, len(jobs), len(india), len(kept))

    stats = {"boards": per_board, "failed_boards": failed, "kept_postings": len(records)}
    return records, stats
