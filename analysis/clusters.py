"""
4.3 What kinds of Data Analyst jobs exist? (clustering)

Each posting is a row of 14 zeros/ones (which skills it mentions). K-means
sorts the postings into K groups so that postings in the same group have
similar skill profiles. We never tell it what the groups mean; we look at
each group's skill profile afterwards and name it.

K = 6, chosen by Dipayan on 2026-09-29 (DECISIONS.md, D20): best separation
score among K=2..6 and the clearest, most distinct job types.

How k-means works, in short:
  1. Drop 6 "centres" into the data.
  2. Assign every posting to its nearest centre.
  3. Move each centre to the average of its postings.
  4. Repeat 2-3 until nothing changes.
n_init=20 runs it 20 times from different starting points and keeps the
best; random_state=42 makes the result identical every time we re-run it.
"""

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from analysis.data import SKILL_LABELS, SKILL_NAMES
from analysis.salary import _city_group

K = 6


def _name_clusters(profiles: pd.DataFrame) -> dict[int, str]:
    """
    Name each cluster by its skill profile (share of postings with each
    skill), so names stay correct when the data changes and we re-run.
    Picked greedily, most distinctive profile first.
    """
    remaining = set(profiles.index)
    names = {}
    rules = [
        ("Few skills listed",       lambda p: -p[SKILL_NAMES].sum()),
        ("Cloud data analyst",      lambda p: p[["azure", "aws", "etl"]].mean()),
        ("BI / dashboard analyst",  lambda p: p[["tableau", "power_bi"]].mean()),
        ("Python + SQL analyst",    lambda p: p["python"]),
        ("Excel / reporting analyst", lambda p: p["excel"]),
    ]
    for name, score in rules:
        best = max(remaining, key=lambda c: score(profiles.loc[c]))
        names[best] = name
        remaining.remove(best)
    for c in remaining:  # whatever is left: communication/stakeholder heavy, few tools
        names[c] = "Business-facing analyst"
    return names


def assign(df: pd.DataFrame) -> tuple[pd.Series, float]:
    """Returns each posting's job type, and the separation (silhouette) score."""
    X = df[SKILL_NAMES].to_numpy()
    km = KMeans(n_clusters=K, n_init=20, random_state=42).fit(X)
    profiles = df[SKILL_NAMES].groupby(km.labels_).mean()
    names = _name_clusters(profiles)
    score = silhouette_score(X.astype(bool), km.labels_, metric="jaccard")
    return pd.Series(km.labels_, index=df.index).map(names), score


def type_all(df_fit: pd.DataFrame, df_other: pd.DataFrame) -> pd.Series:
    """
    Hybrid population (D32): job types are DEFINED on Data Analyst postings
    only (df_fit), then every posting in df_other (e.g. Data Analyst + the
    related analyst titles) is sorted into its nearest type. Same seed and
    settings as assign(), so the types are identical.
    """
    km = KMeans(n_clusters=K, n_init=20, random_state=42).fit(df_fit[SKILL_NAMES].to_numpy())
    names = _name_clusters(df_fit[SKILL_NAMES].groupby(km.labels_).mean())
    return pd.Series(km.predict(df_other[SKILL_NAMES].to_numpy()), index=df_other.index).map(names)


def summary(df: pd.DataFrame, job_type: pd.Series) -> pd.DataFrame:
    """One row per job type: size, how many skills, pay, and skill profile."""
    d = df.assign(job_type=job_type, n_skills=df[SKILL_NAMES].sum(axis=1))
    rows = []
    for name, g in d.groupby("job_type"):
        row = {"job_type": name, "postings": len(g),
               "avg_skills_listed": g["n_skills"].mean(),
               "salaried_postings": int(g["salary_annual"].notna().sum()),
               "median_salary": g["salary_annual"].median()}
        row.update({f"share_{SKILL_LABELS[k]}": g[k].mean() for k in SKILL_NAMES})
        rows.append(row)
    return pd.DataFrame(rows).sort_values("postings", ascending=False)


def pay_at_same_level(df: pd.DataFrame, job_type: pd.Series) -> pd.DataFrame:
    """
    Pay by job type, compared at the same experience level and city
    (a regression with job type instead of skills). Baseline: the
    BI / dashboard analyst type.
    """
    s = df.assign(job_type=job_type)
    s = s[s["salary_annual"].notna()].copy()
    s["log_salary"] = np.log(s["salary_annual"])
    s["city_group"] = s["city"].map(_city_group)
    base = "BI / dashboard analyst"
    role = " + C(role)" if s["role"].nunique() > 1 else ""  # Data Analyst vs related titles (D32)
    res = smf.ols(f"log_salary ~ C(job_type, Treatment('{base}'))"
                  " + C(experience_level, Treatment('unspecified'))"
                  " + C(city_group, Treatment('Other / unknown'))" + role, data=s).fit(cov_type="HC3")
    ci = res.conf_int()
    rows = [{"job_type": base, "pct_vs_bi_dashboard": 0.0, "pct_low": np.nan, "pct_high": np.nan,
             "salaried_postings": int((s.job_type == base).sum())}]
    for name in res.params.index:
        if name.startswith("C(job_type"):
            jt = name.split("[T.")[1].rstrip("]")
            rows.append({"job_type": jt,
                         "pct_vs_bi_dashboard": 100 * (np.exp(res.params[name]) - 1),
                         "pct_low": 100 * (np.exp(ci.loc[name, 0]) - 1),
                         "pct_high": 100 * (np.exp(ci.loc[name, 1]) - 1),
                         "salaried_postings": int((s.job_type == jt).sum())})
    return pd.DataFrame(rows)
