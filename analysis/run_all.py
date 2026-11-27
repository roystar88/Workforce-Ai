"""
Run the whole Phase 4 analysis and write every result to results/.

Usage (after build_db and cleaning):

    python -m analysis.run_all

results/ holds ONLY aggregated numbers (shares, % effects, counts), never
individual job postings, so it's safe to publish in the public repo (D15).
The dashboard reads these files; it never touches the API or raw data.
"""

import json
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analysis import clusters, companies, demand, market, salary
from analysis.data import SKILL_LABELS, SKILL_NAMES, load
from database.build_db import DB_PATH

RESULTS = Path(__file__).resolve().parent.parent / "results"


def skill_quadrant(demand_overall: pd.DataFrame, effects: pd.DataFrame) -> pd.DataFrame:
    """
    The signature view (D19): how COMMON is each skill vs does it PAY?

    Pay signal (careful wording, no overclaiming):
      "leans higher pay"  - effect positive in ALL four model versions
      "leans lower pay"   - effect negative in ALL four
      "unclear"           - the versions disagree
    Separately, `certain` is True only when the main model's 95% range
    excludes zero. "Leans" is a consistent direction, not proof.

    Demand: "common" = asked for in at least 1 in 4 postings (25%).
    """
    main = effects[effects["model"].str.startswith("main")].set_index("skill")
    signs = effects.dropna(subset=["pct_effect"]).groupby("skill")["pct_effect"].agg(
        lambda x: "leans higher pay" if (x > 0).all() else
                  "leans lower pay" if (x < 0).all() else "unclear")
    q = demand_overall.set_index("skill")[["share"]].rename(columns={"share": "demand_share"})
    q = q.join(main[["pct_effect", "pct_low", "pct_high", "verdict", "postings_with_skill"]])
    q["pay_signal"] = signs.reindex(q.index).fillna("not enough data")
    q["certain"] = (q["pct_low"] > 0) | (q["pct_high"] < 0)
    common = q["demand_share"] >= 0.25
    q["quadrant"] = [
        "Not enough salary data" if sig == "not enough data" else
        ("Common + leans higher pay" if c else "Niche + leans higher pay") if sig == "leans higher pay" else
        ("Common, no pay edge" if c else "Niche, no pay edge")
        for c, sig in zip(common, q["pay_signal"])
    ]
    return q.reset_index()


def main() -> None:
    warnings.filterwarnings("ignore")  # statsmodels/sklearn chatter; results are printed below
    RESULTS.mkdir(exist_ok=True)
    # Hybrid population (D32): skills, job types, levels, explorer and the resume
    # check use Data Analyst postings only; the salary models use the bigger pool
    # (Data Analyst + the close analyst titles of D16), with job title as a control.
    pool, pool_all = load(), load(all_ages=True)
    df = pool[pool["role"] == "Data Analyst"].reset_index(drop=True)

    # 4.1 demand
    d_overall = demand.skill_demand(df)
    d_level = demand.skill_demand(df[df["experience_level"] != "unspecified"], by="experience_level")
    # 4.2 salary
    effects = salary.run(pool, pool_all)
    # 4.3 job types
    job_type, sil = clusters.assign(df)
    types = clusters.summary(df, job_type)
    type_pay = clusters.pay_at_same_level(pool, clusters.type_all(df, pool))
    # 4.4 company types
    comp = companies.compare(df, job_type)
    quad = skill_quadrant(d_overall, effects)

    outputs = {
        "skill_demand.csv": d_overall, "skill_demand_by_level.csv": d_level,
        "salary_effects.csv": effects, "skill_quadrant.csv": quad,
        "job_types.csv": types, "job_type_pay.csv": type_pay, "company_types.csv": comp,
    }
    # Dashboard views (D21)
    da, roles = market.add_tags(df), market.all_roles()
    for group in (market.city_tables(da, roles), market.skill_combinations(da),
                  market.experience_tables(da), market.salary_tables(da, roles),
                  market.company_tables(roles), market.tag_tables(da)):
        outputs.update(group)
    outputs.update({"title_mix.csv": market.title_mix(roles), "freshness.csv": market.freshness(),
                    "trends.csv": market.trends(), "explorer.csv": market.explorer_table(da, job_type)})
    (RESULTS / "overview.json").write_text(json.dumps(market.overview(da, roles), indent=2) + "\n")

    for name, table in outputs.items():
        table.round(4).to_csv(RESULTS / name, index=False)

    con = sqlite3.connect(DB_PATH)
    runs = pd.read_sql("SELECT MIN(started_at) AS first, MAX(started_at) AS last, COUNT(*) AS n FROM runs", con)
    con.close()
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_window": {"first_run": runs["first"][0], "last_run": runs["last"][0], "runs": int(runs["n"][0])},
        "population": "Data Analyst postings in India with skills checked, excluding internships, "
                      "posted within 1 year of last sighting",
        "salary_population": "Data Analyst + close analyst titles (BI, business intelligence, Power BI, product, "
                             "reporting, MIS, insights analyst), job title as a control",
        "postings": len(df),
        "salaried_postings_main_model": int(pool["salary_annual"].notna().sum()),
        "salaried_da_postings": int(df["salary_annual"].notna().sum()),
        "job_type_separation_score": round(float(sil), 3),
        "skills": {k: SKILL_LABELS[k] for k in SKILL_NAMES},
        "attribution": "Job and salary data: The Adzuna API (https://www.adzuna.in)",
    }
    (RESULTS / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    print(f"population {len(df)} DA postings; salary pool {len(pool)} postings, {meta['salaried_postings_main_model']} salaried")
    print(quad[["skill", "demand_share", "pct_effect", "pay_signal", "certain", "quadrant"]]
          .sort_values("demand_share", ascending=False).round(2).to_string(index=False))
    print(f"\nwrote {len(outputs) + 1} files to {RESULTS}")


if __name__ == "__main__":
    main()
