"""
Collection settings — WHAT we collect and HOW MUCH.

This is the one file you (or Sayak) should edit to change the search, without
touching any of the fetching logic. Every setting has a comment explaining
why it has the value it has; if you change one, log it in DECISIONS.md,
because changing the search mid-collection changes what the trend lines mean.
"""

# ---------------------------------------------------------------------------
# Adzuna (main source: volume + salary)
# Docs: https://developer.adzuna.com/docs/search
# ---------------------------------------------------------------------------

ADZUNA_COUNTRY = "in"  # India

# We search job TITLES only (Adzuna's `title_only` parameter). Searching the
# full description for e.g. "analytics" would pull in software engineers,
# marketers, etc. whose JD merely mentions analytics.
#
# The list is deliberately broader than "Data Analyst" (decision D2 in
# DECISIONS.md): we can always filter OUT later, but we can never go back in
# time and collect a week we skipped.
ADZUNA_SEARCH_TERMS = [
    "data analyst",
    "business analyst",
    "product analyst",
    "bi analyst",
    "business intelligence",
    "power bi",
    "reporting analyst",
    "mis analyst",       # "MIS" roles are very common in Indian postings
    "insights analyst",
    "analytics",         # catches "Analytics Manager", "Analytics Engineer", ...
]

# Fetch EVERY currently-open posting each week, not just new ones (decision D7).
# A weekly snapshot of all open jobs lets us measure both "what's new this week"
# (via each posting's created date) and "what stays open for weeks".
# Set to a number N to fetch only postings created in the last N days instead.
ADZUNA_MAX_DAYS_OLD = None

ADZUNA_RESULTS_PER_PAGE = 50   # Adzuna's maximum page size

# Free-tier limits: 25 calls/minute, 250/day, 1000/week.
# These caps keep one weekly run safely inside them.
# Probe on 2026-09-27: biggest term had 1,941 open postings (39 pages) and
# all terms together needed ~130 calls. 40 pages leaves a little headroom.
ADZUNA_MAX_PAGES_PER_TERM = 40      # at most 2,000 postings per search term
ADZUNA_MAX_CALLS_PER_RUN = 200      # hard stop, below the 250/day limit
ADZUNA_SECONDS_BETWEEN_CALLS = 3.0  # = 20 calls/minute, below the 25/min limit


# ---------------------------------------------------------------------------
# Skill tagging via Adzuna (decisions D9, D10)
#
# Adzuna only RETURNS the first 500 characters of a description, but it
# SEARCHES the full text. So for each skill we ask: "which 'data analyst'
# postings mention <skill>?", and tag the returned posting ids with it.
# ---------------------------------------------------------------------------

# Which titles get skill tags in the weekly run. Each must be one of
# ADZUNA_SEARCH_TERMS so the tagged postings line up with the collected ones.
# (D10: API budget.)
SKILL_TAG_TITLES = ["data analyst"]

# Close analyst roles, tagged only in one-off runs (`--extra-titles`) to
# roughly double the salaried sample for the regression (D16). Each title
# costs 16+ calls, so these never run on a Monday alongside the weekly run.
SKILL_TAG_EXTRA_TITLES = [
    "bi analyst", "business intelligence", "power bi", "product analyst",
    "reporting analyst", "mis analyst", "insights analyst",
]

# Skills don't change once a job is posted, so each weekly run only tags
# postings created in the last 10 days (same overlap logic as above).
# A one-off backfill (`--backfill`) tags ALL currently open postings.
SKILL_TAG_MAX_DAYS_OLD = 10
# Hard stop, below the 250/day limit. If it's hit, the run fails and saves
# NOTHING, never half-tagged data. Check the day's other calls first.
SKILL_TAG_MAX_CALLS_PER_RUN = 240

# skill name -> list of Adzuna queries; a posting gets the tag if ANY query
# matches it. Each query costs at least 1 API call, so most skills use one.
#   "what":        this word appears (Adzuna matches whole words: "sql" does NOT match "mysql")
#   "what_or":     at least one of these words appears (for spelling variants)
#   "what_phrase": this exact phrase appears
# ⚠ Adding a skill later means older weeks were never tagged with it.
#   Log any change here in DECISIONS.md.
# 14 skills chosen by Dipayan & Sayak on 2026-09-27 (D10): the ones judged most
# relevant for data analyst hiring in India right now.
SKILLS = {
    # core
    "sql":              [{"what_or": "sql mysql postgresql postgres"}],
    "excel":            [{"what": "excel"}],
    "python":           [{"what": "python"}],
    # visualization
    "power_bi":         [{"what_phrase": "power bi"}, {"what": "powerbi"}],
    "tableau":          [{"what": "tableau"}],
    # statistics
    "statistics":       [{"what_or": "statistics statistical"}],
    "ab_testing":       [{"what_phrase": "a/b testing"}],
    "machine_learning": [{"what_phrase": "machine learning"}],
    # data / cloud
    "etl":              [{"what": "etl"}],
    "aws":              [{"what": "aws"}],
    "azure":            [{"what": "azure"}],
    # soft skills
    "stakeholder":      [{"what_or": "stakeholder stakeholders"}],
    "communication":    [{"what_or": "communication communicate"}],
    # new
    "generative_ai":    [{"what_phrase": "generative ai"}, {"what_or": "genai llm llms"}],
}


# Extra tags for the dashboard (D21): NOT skills, so they're kept out of the
# 14-skill analyses. Same full-text trick, run once with `--extra-tags`.
EXTRA_TAGS = {
    "mode_remote":     [{"what_or": "remote wfh"}, {"what_phrase": "work from home"}],
    "mode_hybrid":     [{"what": "hybrid"}],
    "edu_degree":      [{"what_or": "bachelor bachelors degree graduate graduation btech"}],
    "edu_masters":     [{"what_or": "masters mba postgraduate"}],
    "ai_chatgpt":      [{"what_or": "chatgpt openai"}],
    "ai_copilot":      [{"what": "copilot"}],
    "ai_automation":   [{"what": "automation"}],
    "ai_general":      [{"what_phrase": "artificial intelligence"}],
}


# ---------------------------------------------------------------------------
# Company job boards (supplement: FULL job descriptions)
# These are public APIs that companies' own careers pages are built on.
# One request per company per run.
# ---------------------------------------------------------------------------

# Slugs verified on 2026-09-27 to have India-based openings. (Beware: the same
# slug can belong to a different company, e.g. greenhouse/slice is NOT the
# Indian fintech. Check the job locations before adding one.)
# To add a company: find its careers page; if the job links go to
# boards.greenhouse.io/<slug>, jobs.lever.co/<slug> or jobs.ashbyhq.com/<slug>,
# add <slug> to the matching list below.
GREENHOUSE_BOARDS = [
    "razorpaysoftwareprivatelimited", "groww", "zetaglobal", "inmobi", "druva",
    "rubrik", "stripe", "airbnb", "databricks", "zscaler", "agoda",
    "figma", "coinbase",
]
LEVER_BOARDS = [
    "meesho", "cred", "paytm", "zeta", "mindtickle", "fampay",
]
ASHBY_BOARDS = [
    "atlan", "tekion", "snowflake", "confluent", "notion",
]

# Company boards list jobs worldwide, so we keep only India-based ones.
# Matched case-insensitively against the job's location text.
# NOTE: plain "Remote" is NOT here: it usually means remote-from-the-US.
INDIA_LOCATION_KEYWORDS = [
    "india", "bengaluru", "bangalore", "mumbai", "pune", "hyderabad", "delhi",
    "gurgaon", "gurugram", "noida", "chennai", "kolkata", "ahmedabad", "jaipur",
    "kochi", "coimbatore", "chandigarh", "indore",
]

# ...and only analyst-adjacent titles (still broad, per decision D2).
# Matched as whole words, case-insensitively, against the job title.
ATS_TITLE_KEYWORDS = [
    "analyst", "analytics", "data", "insight", "insights",
    "business intelligence", "bi", "reporting", "mis",
]
