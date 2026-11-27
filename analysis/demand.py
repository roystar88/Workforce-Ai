"""
4.1 Skill demand: what share of job postings mention each skill?

The simplest possible analysis, and often the most useful one: for each
skill, (postings mentioning it) / (all postings). The mean of a 0/1 column
IS that share, which is why we can use .mean() below.
"""

import pandas as pd

from analysis.data import SKILL_LABELS, SKILL_NAMES


def skill_demand(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Share of postings mentioning each skill, overall or per group (e.g. by experience)."""
    if by is None:
        out = df[SKILL_NAMES].mean().rename("share").to_frame()
        out["postings"] = len(df)
    else:
        out = df.groupby(by)[SKILL_NAMES].mean().T.melt(ignore_index=False, var_name=by, value_name="share")
        out["postings"] = out[by].map(df[by].value_counts())
    out.index = out.index.map(SKILL_LABELS)
    out.index.name = "skill"
    return out.reset_index()
