"""
Tag Adzuna postings with skills, using Adzuna's own full-text search.

The problem (DECISIONS.md, D9): the API only gives us 500 characters of each
description, and the skills list is usually in the part that's cut off.

The trick: Adzuna SEARCHES the full description even though it only RETURNS
500 characters. So instead of reading the text ourselves, we ask Adzuna one
question per skill:

    "Which postings titled 'data analyst' mention python?"  -> ids {111, 222, ...}

and record (posting id, "python") for every id it returns. Across all skills
that gives each posting its full skill list, including salaried postings,
which is what the salary regression needs.
"""

import logging
from datetime import datetime, timezone

from collector import config
from collector.adzuna import _CallBudget, _search_page

log = logging.getLogger(__name__)


def collect(session) -> tuple[list[dict], dict]:
    budget = _CallBudget(config.SKILL_TAG_MAX_CALLS_PER_RUN)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    titles, max_days_old = config.SKILL_TAG_TITLES, config.SKILL_TAG_MAX_DAYS_OLD

    records, per_skill, truncated = [], {}, []
    for title in titles:
        per_skill[title] = {}
        for skill, queries in config.SKILLS.items():
            ids: set[str] = set()  # a set: the same posting may match two queries of one skill
            for query in queries:
                page, fetched = 1, 0
                while True:
                    data = _search_page(session, budget, title, page, max_days_old, extra=query)
                    results = data.get("results", [])
                    ids.update(str(job["id"]) for job in results)
                    fetched += len(results)
                    if not results or fetched >= data.get("count", 0):
                        break
                    if page >= config.ADZUNA_MAX_PAGES_PER_TERM:
                        truncated.append(f"{title}/{skill}")
                        break
                    page += 1

            # One record per (posting, skill) pair. We don't store the job
            # itself again: the main Adzuna collection already has it.
            for job_id in sorted(ids):
                records.append({
                    "source": "adzuna_skills",
                    "source_job_id": job_id,
                    "skill": skill,
                    "title_term": title,
                    "fetched_at": fetched_at,
                })
            per_skill[title][skill] = len(ids)
            log.info("%-22s skill %-17s tagged=%d", title, skill, len(ids))

    stats = {
        "api_calls": budget.used,
        "title_terms": titles,
        "max_days_old": max_days_old,  # None = backfill of every open posting
        "skills_queried": config.SKILLS,  # exact queries, so we know what each run meant
        "per_skill": per_skill,
        "truncated_skills": truncated,
    }
    return records, stats
