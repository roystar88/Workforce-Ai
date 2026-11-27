"""
4.4 Do different kinds of companies hire for different skills?

Tests Dipayan's original hypothesis (README):
  - IT services firms want BREADTH: many tools per posting
  - product companies want SQL depth + ONE viz tool + communication

Measured on labelled companies only (cleaning/company_types.csv). Company
types with fewer than MIN_POSTINGS postings are left out: shares based on a
handful of postings are too noisy to compare.
"""

import pandas as pd

from analysis.data import SKILL_LABELS, SKILL_NAMES

MIN_POSTINGS = 20
_SKIP = {"Unlabelled", "Anonymous"}


def compare(df: pd.DataFrame, job_type: pd.Series) -> pd.DataFrame:
    d = df.assign(job_type=job_type, n_skills=df[SKILL_NAMES].sum(axis=1))
    viz_tools = d["tableau"] + d["power_bi"]
    # The "product company pattern" from the hypothesis, as a yes/no per posting.
    d["product_pattern"] = (d["sql"] == 1) & (viz_tools == 1) & (d["communication"] == 1)
    rows = []
    for ctype, g in d.groupby("company_type"):
        if ctype in _SKIP or len(g) < MIN_POSTINGS:
            continue
        row = {"company_type": ctype, "postings": len(g),
               "avg_skills_listed": g["n_skills"].mean(),
               "share_product_pattern": g["product_pattern"].mean(),
               "most_common_job_type": g["job_type"].value_counts().index[0],
               "most_common_job_type_share": g["job_type"].value_counts(normalize=True).iloc[0]}
        row.update({f"share_{SKILL_LABELS[k]}": g[k].mean() for k in SKILL_NAMES})
        rows.append(row)
    return pd.DataFrame(rows).sort_values("postings", ascending=False)
