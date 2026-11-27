"""
Loads the analysis population: one row per job posting, one 0/1 column per skill.

Who is in it (DECISIONS.md, D18/D19):
  - postings whose skills were actually checked (skill_tagged_postings)
  - not internships
  - posted within 1 year of when we last saw them (the main window)
    ... unless all_ages=True, used for the robustness check.
"""

import sqlite3

import pandas as pd

from collector.config import SKILLS
from database.build_db import DB_PATH

SKILL_NAMES = list(SKILLS)  # the 14 skills, in the order defined in config.py

# Friendly labels for charts and tables.
SKILL_LABELS = {
    "sql": "SQL", "excel": "Excel", "python": "Python", "power_bi": "Power BI",
    "tableau": "Tableau", "statistics": "Statistics", "ab_testing": "A/B testing",
    "machine_learning": "Machine learning", "etl": "ETL", "aws": "AWS", "azure": "Azure",
    "stakeholder": "Stakeholder mgmt", "communication": "Communication",
    "generative_ai": "Generative AI",
}


def load(all_ages: bool = False) -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM postings_clean WHERE skills_checked AND NOT is_internship", con)
    tags = pd.read_sql("SELECT posting_id, skill FROM posting_skills", con)
    con.close()

    if not all_ages:
        df = df[df["posted_within_1y"] == 1]

    # "Pivot" the long list of (posting, skill) pairs into one column per
    # skill: 1 if the posting mentions it, 0 if not.
    wide = pd.crosstab(tags["posting_id"], tags["skill"]).clip(upper=1)
    wide = wide.reindex(columns=SKILL_NAMES, fill_value=0)
    df = df.merge(wide, left_on="posting_id", right_index=True, how="left")
    df[SKILL_NAMES] = df[SKILL_NAMES].fillna(0).astype(int)

    # Data Analyst titles vs the close analyst titles added in D16.
    df["role"] = df["search_terms"].fillna("").str.contains("data analyst").map(
        {True: "Data Analyst", False: "Related analyst"})
    return df.reset_index(drop=True)
