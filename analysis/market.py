"""
Market-level views for the dashboard (D21): cities, salaries, skill
combinations, freshness, fresher reality, work mode, education, AI demand,
top companies, trends, and the de-identified explorer table.

Two populations, always labelled in the output:
  "Data Analyst"     - the core population from analysis/data.py (skills known)
  "All analyst roles" - every collected analyst-type posting (all 10 search
                        terms), used where more volume is needed (city pay,
                        title mix, companies). Skills are NOT known for most of
                        these, so skill views never use this population.
Both exclude internships and use postings posted within 1 year.
"""

import itertools
import sqlite3

import numpy as np
import pandas as pd

from analysis.data import SKILL_LABELS, SKILL_NAMES
from collector.config import EXTRA_TAGS
from database.build_db import DB_PATH

MIN_CITY_SALARIED = 10   # show a city's pay only if at least this many salaried postings
MIN_CITY_POSTINGS = 30   # show a city's skill profile only if at least this many DA postings

TAG_LABELS = {
    "mode_remote": "Remote / WFH", "mode_hybrid": "Hybrid",
    "edu_degree": "Degree mentioned", "edu_masters": "Master's / MBA mentioned",
    "ai_chatgpt": "ChatGPT / OpenAI", "ai_copilot": "Copilot",
    "ai_automation": "Automation", "ai_general": "\"Artificial intelligence\"",
}


def all_roles() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM postings_clean WHERE NOT is_internship AND posted_within_1y", con)
    con.close()
    return df


def add_tags(da: pd.DataFrame) -> pd.DataFrame:
    """Attach the extra tags (work mode, education, AI) as 0/1 columns."""
    con = sqlite3.connect(DB_PATH)
    tags = pd.read_sql("SELECT posting_id, skill FROM posting_skills", con)
    con.close()
    tags = tags[tags["skill"].isin(EXTRA_TAGS)]
    wide = pd.crosstab(tags["posting_id"], tags["skill"]).clip(upper=1).reindex(columns=list(EXTRA_TAGS), fill_value=0)
    out = da.merge(wide, left_on="posting_id", right_index=True, how="left")
    out[list(EXTRA_TAGS)] = out[list(EXTRA_TAGS)].fillna(0).astype(int)
    return out


def overview(da: pd.DataFrame, roles: pd.DataFrame) -> dict:
    known_city = roles[~roles["city"].isin(["Unknown", "Other"])]
    shares = da[SKILL_NAMES].mean()
    return {
        "analyst_postings": len(roles),
        "da_postings": len(da),
        "companies": int(roles.loc[roles["company"] != "Anonymous", "company"].nunique()),
        "da_median_salary": float(da["salary_annual"].median()),
        "da_salaried": int(da["salary_annual"].notna().sum()),
        "top_skill": SKILL_LABELS[shares.idxmax()], "top_skill_share": float(shares.max()),
        "top_city": known_city["city"].value_counts().index[0],
        "top_city_share_of_known": float(known_city["city"].value_counts(normalize=True).iloc[0]),
        "remote_share": float(da["mode_remote"].mean()),
    }


def title_mix(roles: pd.DataFrame) -> pd.DataFrame:
    terms = roles["search_terms"].fillna("company board").str.split("|").explode()
    return terms.value_counts().rename_axis("search_term").reset_index(name="postings")


def city_tables(da: pd.DataFrame, roles: pd.DataFrame) -> dict[str, pd.DataFrame]:
    demand = pd.DataFrame({"all_analyst_postings": roles["city"].value_counts(),
                           "da_postings": da["city"].value_counts()}).fillna(0).astype(int)
    demand = demand.rename_axis("city").reset_index().sort_values("all_analyst_postings", ascending=False)

    sal = roles[roles["salary_annual"].notna()]
    pay = sal.groupby("city")["salary_annual"].agg(
        salaried_postings="count", median="median",
        p25=lambda x: x.quantile(0.25), p75=lambda x: x.quantile(0.75)).reset_index()
    pay["enough_data"] = pay["salaried_postings"] >= MIN_CITY_SALARIED
    pay = pay.sort_values("median", ascending=False)

    big = da["city"].value_counts()
    big = big[(big >= MIN_CITY_POSTINGS) & (~big.index.isin(["Unknown", "Other"]))].index
    skills = (da[da["city"].isin(big)].groupby("city")[SKILL_NAMES].mean()
              .rename(columns=SKILL_LABELS).reset_index())
    skills["postings"] = skills["city"].map(big.to_series().map(da["city"].value_counts()))
    return {"city_demand.csv": demand, "city_salary.csv": pay, "city_skills.csv": skills}


def skill_combinations(da: pd.DataFrame, top: int = 15) -> dict[str, pd.DataFrame]:
    """Share of postings mentioning each pair / triple of skills, plus the full pair matrix."""
    n = len(da)
    rows = []
    for size in (2, 3):
        for combo in itertools.combinations(SKILL_NAMES, size):
            share = da[list(combo)].all(axis=1).mean()
            rows.append({"combination": " + ".join(SKILL_LABELS[k] for k in combo),
                         "skills": size, "share": share, "postings": int(round(share * n))})
    combos = pd.DataFrame(rows).sort_values("share", ascending=False)
    combos = pd.concat([combos[combos.skills == 2].head(top), combos[combos.skills == 3].head(top)])

    X = da[SKILL_NAMES].to_numpy()
    matrix = pd.DataFrame(X.T @ X / n, index=[SKILL_LABELS[k] for k in SKILL_NAMES],
                          columns=[SKILL_LABELS[k] for k in SKILL_NAMES])
    return {"skill_combinations.csv": combos, "skill_cooccurrence.csv": matrix.reset_index(names="skill")}


def freshness() -> pd.DataFrame:
    """How old are the open postings? All analyst roles, ALL ages, so stale ads are visible."""
    con = sqlite3.connect(DB_PATH)
    ages = pd.read_sql("SELECT age_days FROM postings_clean WHERE NOT is_internship AND source = 'adzuna'", con)["age_days"]
    con.close()
    bins = [-1, 7, 30, 90, 365, 10_000]
    labels = ["Last 7 days", "8–30 days", "1–3 months", "3–12 months", "Over 1 year"]
    counts = pd.cut(ages, bins=bins, labels=labels).value_counts().reindex(labels)
    return counts.rename_axis("posted").reset_index(name="postings")


def experience_tables(da: pd.DataFrame) -> dict[str, pd.DataFrame]:
    order = ["junior", "mid", "senior", "unspecified"]
    mix = da["experience_level"].value_counts().reindex(order).fillna(0).astype(int)
    mix = mix.rename_axis("experience_level").reset_index(name="postings")

    yrs = da["years_min"].dropna()
    bands = pd.cut(yrs, bins=[-1, 1, 3, 5, 100], labels=["0–1 years", "1–3 years", "3–5 years", "5+ years"])
    years = bands.value_counts().reindex(["0–1 years", "1–3 years", "3–5 years", "5+ years"])
    years = years.rename_axis("years_required").reset_index(name="postings")
    years["coverage_note"] = f"years stated in {len(yrs)} of {len(da)} postings ({len(yrs) / len(da):.0%})"

    junior = da[da["experience_level"] == "junior"]
    fresher = pd.DataFrame({
        "skill": [SKILL_LABELS[k] for k in SKILL_NAMES],
        "junior_share": junior[SKILL_NAMES].mean().values,
        "all_share": da[SKILL_NAMES].mean().values,
    }).sort_values("junior_share", ascending=False)
    fresher["junior_postings"] = len(junior)
    return {"experience_mix.csv": mix, "experience_years.csv": years, "fresher_skills.csv": fresher}


def salary_tables(da: pd.DataFrame, roles: pd.DataFrame) -> dict[str, pd.DataFrame]:
    edges = [0, 3e5, 5e5, 7.5e5, 10e5, 15e5, 20e5, 30e5, 1e9]
    labels = ["<3L", "3–5L", "5–7.5L", "7.5–10L", "10–15L", "15–20L", "20–30L", "30L+"]
    dist = pd.DataFrame({
        "band": labels,
        "data_analyst": pd.cut(da["salary_annual"].dropna(), edges, labels=labels).value_counts().reindex(labels).values,
        "all_analyst_roles": pd.cut(roles["salary_annual"].dropna(), edges, labels=labels).value_counts().reindex(labels).values,
    })

    sal = roles[roles["salary_annual"].notna()]
    by_level = sal.groupby("experience_level")["salary_annual"].agg(
        salaried_postings="count", median="median").reindex(["junior", "mid", "senior", "unspecified"]).reset_index()
    by_type = sal.groupby("company_type")["salary_annual"].agg(
        salaried_postings="count", median="median").reset_index().sort_values("salaried_postings", ascending=False)
    return {"salary_distribution.csv": dist, "salary_by_level.csv": by_level, "salary_by_company_type.csv": by_type}


def company_tables(roles: pd.DataFrame) -> dict[str, pd.DataFrame]:
    named = roles[roles["company"] != "Anonymous"]
    top = (named.groupby(["company", "company_type"]).size().rename("postings")
           .reset_index().sort_values("postings", ascending=False).head(15))
    mix = roles["company_type"].value_counts().rename_axis("company_type").reset_index(name="postings")
    return {"top_companies.csv": top, "company_type_mix.csv": mix}


def tag_tables(da: pd.DataFrame) -> dict[str, pd.DataFrame]:
    remote, hybrid = da["mode_remote"] == 1, da["mode_hybrid"] == 1
    mode = pd.DataFrame({"work_mode": ["Remote / WFH mentioned", "Hybrid mentioned", "Both mentioned", "Not stated"],
                         "postings": [int((remote & ~hybrid).sum()), int((hybrid & ~remote).sum()),
                                      int((remote & hybrid).sum()), int((~remote & ~hybrid).sum())]})
    ai_cols = ["ai_automation", "ai_general", "ai_copilot", "ai_chatgpt"]
    ai = pd.DataFrame({"term": [TAG_LABELS[c] for c in ai_cols] + ["Generative AI / LLMs"],
                       "share": [da[c].mean() for c in ai_cols] + [da["generative_ai"].mean()]})
    any_ai = da[ai_cols + ["generative_ai"]].max(axis=1).mean()
    ai = pd.concat([ai, pd.DataFrame({"term": ["Any of these"], "share": [any_ai]})], ignore_index=True)
    edu = pd.DataFrame({"requirement": [TAG_LABELS["edu_degree"], TAG_LABELS["edu_masters"]],
                        "share": [da["edu_degree"].mean(), da["edu_masters"].mean()]})
    for t in (mode, ai, edu):
        t["population"] = f"Data Analyst postings (n={len(da)})"
    return {"work_mode.csv": mode, "ai_demand.csv": ai, "education.csv": edu}


def trends() -> pd.DataFrame:
    """Per collection run: open postings, and how many appeared / disappeared vs the previous run."""
    con = sqlite3.connect(DB_PATH)
    s = pd.read_sql("""SELECT r.run_id, r.started_at, s.posting_id FROM sightings s JOIN runs r USING(run_id)
                       JOIN postings p USING(posting_id) WHERE p.source = 'adzuna'""", con)
    con.close()
    rows, prev = [], None
    for run_id, g in s.groupby("run_id", sort=True):
        ids = set(g["posting_id"])
        rows.append({"run": run_id, "date": g["started_at"].iloc[0][:10], "open_postings": len(ids),
                     "new_since_previous": len(ids - prev) if prev is not None else np.nan,
                     "gone_since_previous": len(prev - ids) if prev is not None else np.nan})
        prev = ids
    return pd.DataFrame(rows)


def explorer_table(da: pd.DataFrame, job_type: pd.Series) -> pd.DataFrame:
    """
    De-identified, one row per Data Analyst posting, for the dashboard's
    filter tool. No IDs, titles, company names, text or links: only derived
    attributes, with salary rounded to the nearest ₹0.5L (D21).
    """
    out = pd.DataFrame({
        "city": da["city"], "experience_level": da["experience_level"],
        "company_type": da["company_type"], "job_type": job_type,
        "salary_lakh": (da["salary_annual"] / 1e5 * 2).round() / 2,
        "remote_mentioned": da["mode_remote"], "hybrid_mentioned": da["mode_hybrid"],
    })
    for k in SKILL_NAMES:
        out[SKILL_LABELS[k]] = da[k]
    return out.sample(frac=1, random_state=0).reset_index(drop=True)  # shuffle: no ordering clues
