"""
Fetch job postings from the Adzuna API (India).

How Adzuna search works: you ask for page 1, 2, 3... of results for a search.
Each page returns up to 50 postings plus `count`, the total number of matches.
We keep asking for the next page until we have them all, or hit our caps
(see config.py). That page-by-page loop is called pagination.
"""

import logging
import os
import time
from datetime import datetime, timezone

import requests

from collector import config

log = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


class AdzunaError(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    """Read API keys from environment variables (never hard-code secrets)."""
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise AdzunaError(
            "ADZUNA_APP_ID / ADZUNA_APP_KEY are not set. "
            "Locally: copy .env.example to .env and fill them in. "
            "On GitHub: add them as repository secrets."
        )
    return app_id, app_key


class _CallBudget:
    """Counts API calls so a single run can never exceed the free-tier limit."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def spend(self) -> None:
        if self.used >= self.limit:
            raise AdzunaError(f"call budget of {self.limit} used up")
        # Pause BEFORE every call except the first to stay under 25 calls/min.
        if self.used > 0:
            time.sleep(config.ADZUNA_SECONDS_BETWEEN_CALLS)
        self.used += 1


def _search_page(session, budget, term, page, max_days_old, extra=None) -> dict:
    """
    One API call = one page of results.
    `extra` adds more search filters, e.g. {"what": "python"} to keep only
    postings whose FULL description mentions python (used by adzuna_skills.py).
    """
    app_id, app_key = _credentials()
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "title_only": term,
        "results_per_page": config.ADZUNA_RESULTS_PER_PAGE,
        "sort_by": "date",  # newest first, so if we hit a cap we lose the OLDEST
        "content-type": "application/json",
        **(extra or {}),
    }
    if max_days_old is not None:
        params["max_days_old"] = max_days_old

    budget.spend()
    url = BASE_URL.format(country=config.ADZUNA_COUNTRY, page=page)
    resp = session.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        # Don't use resp.raise_for_status(): its message includes the full
        # URL, which contains our secret app_key. Build a safe message instead.
        raise AdzunaError(f"HTTP {resp.status_code} for term={term!r} page={page}: {resp.text[:200]}")
    return resp.json()


def probe(session) -> list[dict]:
    """
    Cheap check (1 call per term): how many postings match each term?
    Used to decide the collection window before committing to it.
    """
    budget = _CallBudget(config.ADZUNA_MAX_CALLS_PER_RUN)
    rows = []
    for term in config.ADZUNA_SEARCH_TERMS:
        recent = _search_page(session, budget, term, 1, 10)
        everything = _search_page(session, budget, term, 1, None)
        rows.append({
            "term": term,
            "last_10_days": recent.get("count"),
            "all_live": everything.get("count"),
            "pages_needed": -(-everything.get("count", 0) // config.ADZUNA_RESULTS_PER_PAGE),  # ceiling division
        })
    return rows


def collect(session) -> tuple[list[dict], dict]:
    """
    Run every search term, page through results, and return:
      - records: one dict per UNIQUE posting (deduplicated by Adzuna's id)
      - stats:   numbers for the run manifest (calls used, counts per term, ...)
    """
    budget = _CallBudget(config.ADZUNA_MAX_CALLS_PER_RUN)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Keyed by posting id. The same posting often matches several terms
    # (e.g. "Data Analyst - Power BI" matches "data analyst" AND "power bi"),
    # so we store it once and remember every term that found it.
    by_id: dict[str, dict] = {}
    per_term = {}
    truncated_terms = []

    for term in config.ADZUNA_SEARCH_TERMS:
        page, seen_for_term, total = 1, 0, None
        while page <= config.ADZUNA_MAX_PAGES_PER_TERM:
            data = _search_page(session, budget, term, page, config.ADZUNA_MAX_DAYS_OLD)
            total = data.get("count", 0)
            results = data.get("results", [])
            for job in results:
                job_id = str(job["id"])
                if job_id not in by_id:
                    by_id[job_id] = {
                        "source": "adzuna",
                        "source_job_id": job_id,
                        "fetched_at": fetched_at,
                        "search_terms": [],
                        "payload": job,  # the untouched API record
                    }
                by_id[job_id]["search_terms"].append(term)
            seen_for_term += len(results)
            if not results or seen_for_term >= total:
                break
            page += 1
        else:
            # while-loop ended because of the page cap, not because we ran out
            truncated_terms.append(term)

        per_term[term] = {"matched": total, "fetched": seen_for_term}
        log.info("adzuna %-22s matched=%-5s fetched=%s", term, total, seen_for_term)

    stats = {
        "api_calls": budget.used,
        "unique_postings": len(by_id),
        "per_term": per_term,
        "truncated_terms": truncated_terms,  # non-empty => raise caps or narrow terms
        "max_days_old": config.ADZUNA_MAX_DAYS_OLD,
    }
    return list(by_id.values()), stats
