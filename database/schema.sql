-- =============================================================================
-- WorkForce AI: database schema (SQLite)
--
-- Design idea: each FACT is stored in exactly ONE place ("normalization").
--
--   runs                 one row per weekly collection run
--   postings             one row per unique job posting, stored once
--   sightings            "posting X was open during run Y": the time dimension
--   posting_search_terms which of our search terms found each posting
--
-- The tables connect through shared ID columns ("keys"). Queries use JOIN to
-- stitch them back together. Example:
--
--   SELECT r.collection_week, COUNT(*) AS open_postings
--   FROM sightings s
--   JOIN runs r ON r.run_id = s.run_id
--   GROUP BY r.collection_week;
--
-- This file is run by database/build_db.py, which rebuilds the whole database
-- from data/raw/ every time. The raw files are the source of truth. This
-- database is a convenient, queryable copy (see DECISIONS.md, D4).
-- =============================================================================


-- One row per weekly collection run.
CREATE TABLE runs (
    run_id          TEXT PRIMARY KEY,  -- folder name, e.g. '2026-09-27_1330Z'
    started_at      TEXT NOT NULL,     -- ISO timestamp (UTC) when the run started
    collection_week TEXT NOT NULL,     -- ISO week of the run, e.g. '2026-W39'
    adzuna_records  INTEGER,           -- how many postings each source returned
    ats_records     INTEGER
);


-- One row per unique job posting, no matter how many weeks it stayed open.
-- If a posting's details change between weeks, the LATEST version is kept
-- here; every earlier version is still in data/raw/ if we ever need it.
CREATE TABLE postings (
    posting_id          TEXT PRIMARY KEY,  -- '<source>:<id>', e.g. 'adzuna:5412345678'
                                           -- (prefix needed: two sources could reuse the same id)
    source              TEXT NOT NULL,     -- 'adzuna' | 'greenhouse' | 'lever' | 'ashby'
    title               TEXT NOT NULL,
    company_name        TEXT,              -- raw, NOT yet cleaned ('Amazon' vs 'ADCI - Karnataka')
    location_text       TEXT,              -- as displayed by the source
    region              TEXT,              -- state, when the source gives it (Adzuna only)
    city                TEXT,              -- city, when the source gives it (Adzuna only)
    created_at          TEXT,              -- when the EMPLOYER posted it (ISO date-time)
    salary_min          REAL,              -- INR per year as listed, NOT yet cleaned (Adzuna only)
    salary_max          REAL,
    salary_is_predicted INTEGER,           -- 1 = Adzuna's estimate, 0 = employer-listed, NULL = no salary
    description         TEXT,              -- raw text/HTML, NOT yet cleaned
    description_is_full INTEGER NOT NULL,  -- 0 = cut at 500 chars (Adzuna), 1 = full text (company boards)
    category            TEXT,              -- Adzuna's category, e.g. 'IT Jobs'
    contract_time       TEXT,              -- 'full_time' | 'part_time' | NULL
    url                 TEXT
);


-- The time dimension: one row for every (run, posting) pair where the posting
-- was open. A posting open for 3 weeks has 3 rows here, but only 1 in postings.
CREATE TABLE sightings (
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    posting_id  TEXT NOT NULL REFERENCES postings(posting_id),
    PRIMARY KEY (run_id, posting_id)       -- a posting can't be seen twice in one run
);


-- Which of our Adzuna search terms (collector/config.py) found each posting.
-- One posting can match several terms, e.g. 'Data Analyst - Power BI'.
CREATE TABLE posting_search_terms (
    posting_id  TEXT NOT NULL REFERENCES postings(posting_id),
    search_term TEXT NOT NULL,
    PRIMARY KEY (posting_id, search_term)
);


-- Which skills each posting's FULL description mentions, found via Adzuna's
-- full-text search (DECISIONS.md, D9). One row per (posting, skill).
CREATE TABLE posting_skills (
    posting_id  TEXT NOT NULL,             -- joins to postings.posting_id
    skill       TEXT NOT NULL,             -- e.g. 'sql', 'power_bi' (see collector/config.py)
    PRIMARY KEY (posting_id, skill)
);


-- Every skill-tagging run: which titles and which time window it covered.
-- Needed to tell "this posting doesn't mention SQL" apart from
-- "this posting was never checked for SQL".
-- One row per (run, title): a run can tag several titles.
CREATE TABLE skill_tag_runs (
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    started_at   TEXT NOT NULL,
    title_term   TEXT NOT NULL,            -- e.g. 'data analyst'
    max_days_old INTEGER,                  -- NULL = backfill of ALL open postings
    skills_json  TEXT NOT NULL,            -- the exact skill queries used
    PRIMARY KEY (run_id, title_term)
);


-- Indexes = lookup shortcuts, like the index at the back of a book. They make
-- "find all sightings of posting X" fast without scanning every row.
CREATE INDEX idx_sightings_posting ON sightings(posting_id);
CREATE INDEX idx_postings_company  ON postings(company_name);


-- A VIEW is a saved query that behaves like a read-only table.
-- This one answers "when did we first/last see each posting, and how often?"
CREATE VIEW posting_lifespan AS
SELECT
    p.posting_id,
    p.title,
    p.company_name,
    MIN(r.started_at)  AS first_seen,
    MAX(r.started_at)  AS last_seen,
    COUNT(*)           AS runs_seen
FROM postings  p
JOIN sightings s ON s.posting_id = p.posting_id
JOIN runs      r ON r.run_id     = s.run_id
GROUP BY p.posting_id;


-- Postings whose skills we actually know: ones that a skill-tagging run
-- covered (right title, and created inside that run's time window).
-- ONLY for these does "no row in posting_skills" mean "doesn't mention it".
-- (+1 day tolerance: Adzuna's created timestamps can run a few hours ahead.)
CREATE VIEW skill_tagged_postings AS
SELECT DISTINCT t.posting_id
FROM posting_search_terms t
JOIN postings       p   ON p.posting_id = t.posting_id
JOIN skill_tag_runs str ON str.title_term = t.search_term
WHERE str.skills_json LIKE '%"sql"%'   -- only runs that tagged the 14 skills, not --extra-tags runs
  AND julianday(p.created_at) <= julianday(str.started_at) + 1
  AND (str.max_days_old IS NULL
       OR julianday(p.created_at) >= julianday(str.started_at) - str.max_days_old);
