-- =============================================================================
-- Example queries: a SQL tour of our database, from simple to harder.
--
-- Run them all:     sqlite3 -box data/workforce.db < database/example_queries.sql
-- Or interactively: sqlite3 -box data/workforce.db
--                   then paste any query (end it with ; and press Enter).
--                   Type .tables to list tables, .quit to exit.
-- =============================================================================


-- 1) SELECT + WHERE + LIMIT: look at a few rows.
--    "Show 5 job titles and companies found by the 'data analyst' search."
--    The IN (subquery) part: first find the posting_ids that the search term
--    matched, then keep only postings whose id is in that list.
SELECT title, company_name, city
FROM postings
WHERE posting_id IN (SELECT posting_id FROM posting_search_terms
                     WHERE search_term = 'data analyst')
LIMIT 5;


-- 2) GROUP BY + COUNT + ORDER BY: summarise.
--    "Which companies have the most open postings?"
--    GROUP BY squashes all rows with the same company into one row;
--    COUNT(*) counts how many rows were squashed together.
SELECT company_name, COUNT(*) AS open_postings
FROM postings
GROUP BY company_name
ORDER BY open_postings DESC
LIMIT 10;


-- 3) JOIN: combine two tables.
--    "How many postings did each search term find?"
--    posting_search_terms has the term; postings has the salary.
--    JOIN ... ON lines the rows up wherever posting_id matches.
SELECT t.search_term,
       COUNT(*)                   AS postings,
       COUNT(p.salary_min)        AS with_salary,   -- COUNT(column) skips NULLs
       ROUND(100.0 * COUNT(p.salary_min) / COUNT(*), 1) AS pct_with_salary
FROM posting_search_terms t
JOIN postings p ON p.posting_id = t.posting_id
GROUP BY t.search_term
ORDER BY postings DESC;


-- 4) LIKE + CASE: a first, rough look at skills.
--    "What % of 'data analyst' postings mention each tool?"
--    LIKE '%sql%' = the text contains 'sql' anywhere (% = anything).
--    CASE WHEN ... THEN 1 ELSE 0 END turns yes/no into 1/0, so AVG() = share.
--    ⚠ ROUGH: matching text like this has traps. '%excel%' also matches
--    'excellent'. Doing this properly is exactly what Phase 3 is for.
SELECT
    COUNT(*) AS postings,
    ROUND(100 * AVG(CASE WHEN description LIKE '%sql%'      THEN 1 ELSE 0 END), 1) AS pct_sql,
    ROUND(100 * AVG(CASE WHEN description LIKE '%python%'   THEN 1 ELSE 0 END), 1) AS pct_python,
    ROUND(100 * AVG(CASE WHEN description LIKE '%power bi%' THEN 1 ELSE 0 END), 1) AS pct_power_bi,
    ROUND(100 * AVG(CASE WHEN description LIKE '%tableau%'  THEN 1 ELSE 0 END), 1) AS pct_tableau,
    ROUND(100 * AVG(CASE WHEN description LIKE '%excel%'    THEN 1 ELSE 0 END), 1) AS pct_excel
FROM postings
WHERE posting_id IN (SELECT posting_id FROM posting_search_terms
                     WHERE search_term = 'data analyst');


-- 5) Aggregates on numbers: salaries.
--    "For data analyst postings WITH a listed salary: how many, and what range?"
--    (salary_min + salary_max) / 2 = middle of the advertised range.
--    ⚠ Includes the uncleaned outliers (e.g. ₹78/yr) that Phase 3 will fix,
--    which is why MIN looks absurd. Always sanity-check extremes!
SELECT
    COUNT(*)                                     AS postings_with_salary,
    ROUND(MIN((salary_min + salary_max) / 2))    AS lowest_mid,
    ROUND(AVG((salary_min + salary_max) / 2))    AS average_mid,
    ROUND(MAX((salary_min + salary_max) / 2))    AS highest_mid
FROM postings
WHERE salary_min IS NOT NULL
  AND posting_id IN (SELECT posting_id FROM posting_search_terms
                     WHERE search_term = 'data analyst');


-- 6) The time dimension: sightings JOIN runs.
--    "How many postings were open in each collection week?"
--    Only 1 row today. After a few Mondays this becomes a trend line.
SELECT r.collection_week, COUNT(*) AS open_postings
FROM sightings s
JOIN runs r ON r.run_id = s.run_id
GROUP BY r.collection_week
ORDER BY r.collection_week;
