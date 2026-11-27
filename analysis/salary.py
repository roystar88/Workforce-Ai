"""
4.2 Which skills go with higher advertised pay? (regression)

The idea in one line: predict log(salary) from skills + experience + city
all at once, so each skill's number is its effect with the others held fixed.

    log(salary) = base + b_sql*SQL + b_python*Python + ... + experience + city

Why log(salary)? A coefficient b on a log scale means "about (e^b - 1) x 100
percent higher pay", so results read as percentages, and a ₹1L gap at ₹4L is
not treated the same as a ₹1L gap at ₹25L.

Choices (DECISIONS.md, D19):
  - Ordinary least squares with robust (HC3) standard errors, which don't
    assume every job's salary is equally noisy.
  - A skill only gets an estimate if at least MIN_POSTINGS salaried postings
    have it AND at least MIN_POSTINGS don't. Otherwise the estimate would
    rest on a handful of jobs and we report "not enough data" instead.
  - Controls: experience level and city group (see below).
"""

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from analysis.data import SKILL_LABELS, SKILL_NAMES

MIN_POSTINGS = 15

_METROS = {"Delhi NCR", "Mumbai", "Pune", "Chennai", "Hyderabad"}


def _city_group(city: str) -> str:
    """Only 1-16 salaried jobs per city, so group them into three."""
    if city == "Bengaluru":
        return "Bengaluru"
    return "Other metro" if city in _METROS else "Other / unknown"


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    s = df[df["salary_annual"].notna()].copy()
    s["log_salary"] = np.log(s["salary_annual"])
    s["city_group"] = s["city"].map(_city_group)
    return s


def estimable_skills(s: pd.DataFrame) -> list[str]:
    counts = s[SKILL_NAMES].sum()
    return [k for k in SKILL_NAMES if counts[k] >= MIN_POSTINGS and len(s) - counts[k] >= MIN_POSTINGS]


def fit(s: pd.DataFrame, skills: list[str], controls: bool = True):
    """Fit the model; returns a statsmodels result."""
    terms = list(skills)
    if controls:
        # C(...) = a category: one "switch" per level, compared against a base level.
        terms += ["C(experience_level, Treatment('unspecified'))", "C(city_group, Treatment('Other / unknown'))"]
        if s["role"].nunique() > 1:
            terms.append("C(role)")
    return smf.ols("log_salary ~ " + " + ".join(terms), data=s).fit(cov_type="HC3")


def effects_table(result, s: pd.DataFrame, skills: list[str], label: str) -> pd.DataFrame:
    """Turn coefficients into '% higher pay' with a 95% range."""
    ci = result.conf_int()
    rows = []
    for k in SKILL_NAMES:
        row = {"model": label, "skill": SKILL_LABELS[k], "postings_with_skill": int(s[k].sum()),
               "sample_size": len(s)}
        if k in skills:
            b, (lo, hi) = result.params[k], ci.loc[k]
            row.update(pct_effect=100 * (np.exp(b) - 1), pct_low=100 * (np.exp(lo) - 1),
                       pct_high=100 * (np.exp(hi) - 1), p_value=result.pvalues[k])
            row["verdict"] = ("higher pay" if lo > 0 else "lower pay" if hi < 0 else "no clear effect")
        else:
            row["verdict"] = "not enough data"
        rows.append(row)
    return pd.DataFrame(rows)


def run(df_main: pd.DataFrame, df_all_ages: pd.DataFrame) -> pd.DataFrame:
    """Main model + the three robustness checks, stacked in one table."""
    main = prepare(df_main)
    skills = estimable_skills(main)  # fix the skill list from the MAIN sample for all checks
    no_monthly = main[main["salary_rule"] != "monthly_x12"]
    variants = [
        ("main: posted within 1 year, with controls", main, True),
        ("check: all posting ages", prepare(df_all_ages), True),
        ("check: without the monthly x12 salaries", no_monthly, True),
        ("check: no experience/city controls", main, False),
    ]
    tables = [effects_table(fit(s, skills, c), s, skills, label) for label, s, c in variants]
    return pd.concat(tables, ignore_index=True)


def experience_effects(df_main: pd.DataFrame) -> pd.DataFrame:
    """The control variables' own effects, which are interesting in themselves."""
    s = prepare(df_main)
    result = fit(s, estimable_skills(s))
    ci = result.conf_int()
    rows = []
    for name in result.params.index:
        if name.startswith("C("):
            level = name.split("[T.")[1].rstrip("]")
            rows.append({"factor": name.split(",")[0][2:], "level": level,
                         "pct_effect": 100 * (np.exp(result.params[name]) - 1),
                         "pct_low": 100 * (np.exp(ci.loc[name, 0]) - 1),
                         "pct_high": 100 * (np.exp(ci.loc[name, 1]) - 1)})
    return pd.DataFrame(rows)
