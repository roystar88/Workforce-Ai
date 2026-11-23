# Decision Log

Every choice that shapes the analysis, with the reasoning at the time.
This file is the backbone of the interview story: *why* the numbers mean what
they mean. Newest decisions at the bottom. Never delete an entry. If we change
our minds, add a new entry that supersedes the old one.

---

### D1: Data sources: Adzuna API + public company job-board APIs (2026-09-27)
**Decision:** Collect from the Adzuna India API (volume + salary) and from the
public Greenhouse / Lever / Ashby job-board APIs of companies hiring in India
(full-length descriptions). Do **not** scrape Naukri or Indeed.

**Why:**
- Naukri's and Indeed's terms of service prohibit automated scraping, and both
  run bot protection. A scraper would violate their terms and would likely
  break mid-collection, leaving gaps in a time series that can't be refilled.
- Adzuna is an official API with a free tier, covers India, and returns
  `salary_min` / `salary_max`.
- Adzuna truncates descriptions (~500 chars), which would hurt skill
  extraction. The ATS APIs return full descriptions and are published by the
  companies specifically so their postings can be read programmatically.

**Known limitations (to state honestly in the final write-up):**
- Adzuna often **predicts** a salary when the employer didn't list one
  (`salary_is_predicted = 1`). Those are Adzuna's model output, not market
  data. See D5.
- The company-board source only covers companies that use those three ATSs:
  mostly product/tech companies. IT-services giants (TCS, Infosys, ...) use
  their own portals and are only visible via Adzuna. So the two sources are
  **not** comparable samples. Don't compare counts across sources.
- Adzuna terms: personal research use is allowed, the source must be credited
  ("Jobs by Adzuna"), and listings must not be republished. See D6.

### D2: Scope: collect broad, filter at analysis time (2026-09-27)
**Decision:** Search titles for data analyst, business analyst, product analyst,
BI analyst, business intelligence, Power BI, reporting analyst, MIS analyst,
insights analyst, analytics. (Exact list: `collector/config.py`.)

**Why:** We can always exclude postings later, but we can never go back and
collect a week we skipped. Deciding what counts as "a data analyst job" is a
Phase 3 decision, made with the actual data in front of us.

### D3: Weekly cadence via GitHub Actions (2026-09-27)
**Decision:** Every Monday 09:00 IST, GitHub Actions runs the collector and
commits the snapshot to the repo.

**Why:** Runs even if the laptop is off (missed weeks = broken trend lines),
and every snapshot is visible to collaborators via git history.

### D4: Store raw API responses, untouched, one folder per run (2026-09-27)
**Decision:** Each run writes `data/raw/<run_id>/{adzuna,ats}.jsonl.gz` plus a
`manifest.json` (counts, API calls used, errors). The SQL database (Phase 2) is
*built from* these files and is never the only copy.

**Why:** Parsing rules (what counts as a skill, how to read a salary string)
will evolve. Keeping the raw layer means any improved rule can be re-applied
to all past weeks.

### D5: Regression uses only employer-advertised salaries (planned, 2026-09-27)
**Decision:** In the salary regression, keep only Adzuna postings with
`salary_is_predicted == 0`.

**Why:** Otherwise we'd be regressing Adzuna's own salary model on skills and
"discovering" whatever that model already assumes. Cost: a smaller sample.
We'll report the sample size next to every coefficient.

### D6: Repo privacy (pending)
Raw Adzuna data shouldn't be published. Proposal: keep the repo private during
collection; before making it public, remove `data/raw/` from the public
version and publish only aggregated results, crediting Adzuna.

### D7: Collect every open posting each week, not just new ones (2026-09-27)
**Decision:** `ADZUNA_MAX_DAYS_OLD = None` (all live postings), with
`ADZUNA_MAX_PAGES_PER_TERM = 40`. Supersedes the earlier 10-day default.

**Evidence (probe, 2026-09-27):**

| term | new in last 10 days | all open |
|---|---:|---:|
| data analyst | 265 | 1,152 |
| business analyst | 377 | 1,941 |
| analytics | 377 | 1,699 |
| reporting analyst | 75 | 355 |
| business intelligence | 50 | 304 |
| product analyst | 60 | 278 |
| power bi | 33 | 257 |
| insights analyst | 13 | 77 |
| bi analyst | 20 | 75 |
| mis analyst | 2 | 31 |

Only-new would cost ~31 API calls a week, all-open ~130. Both fit the free tier
(200 cap per run, 250/day).

**Why:** A full snapshot contains everything the new-only pull does (new
postings can still be identified by `created` date) plus how long each posting
stays open. It also gives the salary regression a much larger starting sample
on week 1, and advertised salaries are the scarce resource (D5).

**Watch:** if volumes grow past ~200 calls, the page cap starts cutting the
oldest postings of the biggest terms. `manifest.json` → `truncated_terms`
records when that happens.

---

### D8: Database design: runs / postings / sightings (2026-09-27)
**Decision:** SQLite database (`database/schema.sql`), rebuilt from `data/raw/`
by `python -m database.build_db`. Each posting is stored once in `postings`;
`sightings` records every (run, posting) pair, which is our time dimension.

**Why:** Storing a full copy of every posting every week would duplicate the
same text up to 8 times, and an edit to one copy wouldn't reach the others.
Normalized tables store each fact once and keep all options open (new vs
still-open postings, how long postings stay open) without deciding them now.
If a posting changes between weeks, the latest version is kept in `postings`;
older versions remain in `data/raw/`.

### D9: Adzuna snippets can't be used for skills, but Adzuna's search can (2026-09-27)
**Finding:** Measured on analyst-titled postings, SQL appears in 5.7% of
Adzuna's 500-character snippets but in 60.5% of full-text company-board
postings. The snippets are mostly company intro and responsibilities, and the
skills list is usually cut off. Since salaries exist only on Adzuna and full
text only on company boards, almost no posting had both skills and salary.

**Test:** Adzuna's keyword search (`what=`) matches the FULL description on
Adzuna's side. For `title_only="data analyst"`: sql 778 (68%), python 540 (47%),
excel 500 (43%), tableau 374 (32%) of 1,152, consistent with full-text rates.
26 of the first 50 SQL matches did not show "sql" in the snippet. All returned
IDs were already in our database.

**Decision (in progress):** Tag postings with skills by asking Adzuna one
query per skill, rather than reading snippets. Fetching full descriptions via
`redirect_url` was rejected: that means scraping Adzuna's website and the
original job boards behind it (D1).

### D10: Skill-tag "data analyst" titles only, with 14 skills (2026-09-27)
**Decision:** Each weekly run asks Adzuna, per skill, which `title_only="data
analyst"` postings created in the last 10 days mention it. A one-off
`--backfill` run tags every open posting. Skill list: `collector/config.py`
(`SKILLS`).

**The 14 skills:** SQL, Excel, Python · Power BI, Tableau · statistics,
A/B testing, machine learning · ETL, AWS, Azure · stakeholder, communication
· generative AI / LLM. Chosen from a 22-skill draft by keeping the skills we
judged most relevant for data analyst jobs in India right now. Dropped:
Looker, Qlik, Snowflake, BigQuery, Databricks, SAS, VBA, Alteryx. A smaller
list also keeps the salary regression more reliable, since only a few hundred
postings list a salary (roughly 10+ salaried postings per skill we estimate).

**Why only Data Analyst titles:** API budget. The free tier allows 250 calls/day
and 2,500/month, and the weekly collection already uses ~560/month. Tagging
DA titles costs ~120 calls once, then ~40/week. Adding the close analyst
titles would cost ~180/week, and all 10 terms would exceed the monthly limit.
Can be expanded later if the budget allows.

**Known limits:**
- R can't be tracked: a one-letter search term matches everything.
- Adzuna matches whole words: "sql" doesn't match "MySQL", so variants are
  listed explicitly.
- A skill added later has no tags for earlier weeks. `skill_tag_runs` records
  which queries each run used, and the `skill_tagged_postings` view marks
  which postings were actually checked.

### D11: Licence check: we use Adzuna under "Personal research", with no time limit and no cost (2026-09-29)
**Question raised:** Adzuna's API terms mention a 14-day trial. Does it apply
to us, and could the project ever cost money?

**What the terms say** (developer.adzuna.com/docs/terms_of_service, read 2026-09-29):
- Permitted uses: publishing Adzuna listings, publishing salary estimates,
  and **"Personal research"**. No time limit is attached to these.
- The 14-day trial covers *"any other use of the Adzuna API by a commercial,
  government or academic organisation"*, for validating data coverage and
  quality.
- Personal/academic research obligation: acknowledge Adzuna ("The Adzuna
  API", with a link) as the source of all salary and vacancy data wherever
  it's published.
- On termination: remove Adzuna data from any web pages.
- The terms mention no fees, payments or billing.

**Conclusion:** Two individuals doing a non-commercial portfolio project =
personal research, so the 14-day trial doesn't apply. No payment method is
attached to any account the project uses (Adzuna, GitHub), so it can't
generate a bill. If the project ever became commercial, a licence from
Adzuna would be needed first.

**Safeguards:** API keys live only in the git-ignored `.env` and in GitHub
Secrets (verified: never committed). Each run is capped at 200 Adzuna calls.
Rule: never attach a payment method to any account this project uses.

### D12: Run collection indefinitely, not just 6–8 weeks (2026-09-29)
**Decision:** The weekly collection keeps running with no end date. The
first full analysis happens after ~8 weeks (late Nov 2026); after that the
analysis and dashboard refresh weekly.

**Why:** A continuously running pipeline with a growing time series is a
stronger result than a one-off 2-month study, and longer windows make the
trend analysis more reliable.

**Checked sustainable at ₹0:** Adzuna ~700 of 2,500 calls/month, and
personal research has no time limit (D11). GitHub Actions ~52 of 2,000
free minutes/month. Repo grows ~1.75 MB/week (~90 MB/year), well within
GitHub's recommended ~1 GB per repo for about 10 years. Revisit storage if
it approaches that.

**Implication for analysis:** 8 weeks is the first milestone, not the
whole window. Trend analysis should use rolling windows (e.g. last 8 weeks
vs previous 8) so it stays meaningful as data accumulates.

### D13: Finish fast, then collect on demand (supersedes D12) (2026-09-29)
**Decision:** Complete phases 3–5 now, using the data already collected
(target: ~1–2 weeks), instead of waiting ~8 weeks. Keep the automatic Monday
run only while we build. Once the dashboard is done, remove the schedule and
collect **on demand** via GitHub's "Run workflow" button.

**Why:** Demand shares, the salary regression and clustering all work on a
single large snapshot (~5,600 open postings, ~190 salaried Data Analyst
postings after the skill backfill). Only week-over-week trends need many
runs; the trend view will show however many runs exist and grow with each
on-demand run. A project that's finished and presentable soon is worth more
to the job search than a longer study.

**Caveat to state honestly:** with a few weeks of data, "rising/fading"
results are early signals, not established trends.

### D14: Manual-mode rules and shutdown plan (2026-09-29)
**Context:** This is an interview-portfolio project, not a long-term tool.
After the dashboard is done, collection switches to on demand (D13), and
the whole thing will be shut down after the job search.

**Decisions:**
- When switching to manual, remove the `schedule:` trigger from the workflow
  (keep `workflow_dispatch`). Nothing then runs, and no API key is used,
  unless someone presses "Run workflow".
- Manual runs must skill-tag **all open** Data Analyst postings, not just
  the last 10 days. After a long gap most open postings are older than 10
  days and would otherwise never be tagged. Cost: ~130 + ~90 = ~220 Adzuna
  calls per run, under the 250/day limit.
- Before any manual run after a long gap, re-read Adzuna's API terms for
  changes (fees, trial periods, limits) before running.
- Before sharing with interviewers: publish a public version with code,
  docs and aggregated results only, without `data/raw/` (D6, Adzuna terms).

**Shutdown checklist** (when the project is no longer needed):
1. GitHub → Settings → Secrets → Actions: delete `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`.
2. Delete `.env` locally.
3. GitHub → Actions → Weekly job collection → Disable workflow.
4. Optional: email info@adzuna.com to close the API account (terms allow
   either party to terminate by email). On termination, remove Adzuna data
   from any published web pages.

### D15: Collect for 2 weeks, then freeze; public code and results, private raw data (supersedes D6, D13, D14 where they differ) (2026-09-29)
**Decision:**
1. Collection runs until the scheduled run on **Mon 12 Oct 2026** (4 snapshots:
   27 Sep, 28 Sep, 5 Oct, 12 Oct, plus the one-off skill backfill).
2. Then **freeze**: disable the workflow and delete the Adzuna keys everywhere
   (GitHub Secrets and `.env`), optionally closing the Adzuna account. After
   that no key exists, so no API call or bill is possible whatever Adzuna's
   future terms say.
3. Cleaning, analysis and the dashboard are built on the frozen dataset.
4. Two repositories: **public** `workforce-ai` (code, docs, aggregated result
   files, dashboard) with `data/raw/` stripped from history, and **private**
   `workforce-ai-data` (raw Adzuna data backup).
5. The dashboard reads aggregated result files, never the API or raw data, so
   anyone can run it without keys.

**Why:** Interviewers need to see the code, not just a dashboard. Adzuna's
terms (re-read 2026-09-29): personal research may publish results as long as
Adzuna is acknowledged ("The Adzuna API", with a link); the terms don't
restrict publishing code; raw listings are Adzuna's data, so we don't
republish them. Freezing removes any future API or billing risk.

**Interview demo without a key:** `python -m collector.run_collection --only ats`
collects live postings from public company job boards. Past Adzuna run logs
(`manifest.json`) show the Adzuna part ran. Anyone can get their own free
Adzuna key to reproduce it.

### D16: Final collection schedule and extra skill tagging (2026-09-29)
**Decision:** Also skill-tag the close analyst titles (bi analyst, business
intelligence, power bi, product analyst, reporting analyst, mis analyst,
insights analyst), in one-off runs only. This roughly doubles the salaried
postings with known skills (~190 → ~350), strengthening the regression.

| Date (IST, after 05:30) | Run | ~Adzuna calls |
|---|---|---:|
| Tue 29 Sep | `--only adzuna_skills --backfill` (Data Analyst) | 90 |
| Wed 30 Sep | `--only adzuna_skills --backfill --extra-titles` | 200 |
| Mon 5 Oct, Mon 12 Oct | scheduled weekly runs | 161 each |
| Tue 13 Oct | `--only adzuna_skills --backfill` (final) | 90 |
| Wed 14 Oct | `--only adzuna_skills --backfill --extra-titles` (final), then **FREEZE** | 200 |

**Budget rules:** never more than one big run per day; one-off runs only
after 05:30 IST (00:00 UTC), in case Adzuna counts its daily limit in UTC; no
one-off runs on Mondays. Peak: ~450 calls/week (limit 1,000), under 650 per
calendar month (limit 2,500). `SKILL_TAG_MAX_CALLS_PER_RUN = 240`: if hit,
the run fails and saves nothing rather than half-tagged data.

**Freeze (14 Oct):** as D15. Nothing is collected after that.

### D17: Analysis improvements: control for experience and city, label company types, add an interview pack (2026-09-29)
**Decision:**
1. **Experience level** (from titles like Senior/Lead/Junior and "N years"
   patterns) is extracted in Phase 3 and used as a control in the salary
   regression.
2. **City/region** is used as a control in the salary regression.
3. **Company type** is hand-labelled for the top ~50 companies (IT services
   / product / bank-financial / consulting / captive centre / staffing) to
   test the hypothesis that IT services hire for tool breadth while product
   companies want SQL + one viz tool + communication.
4. An **interview pack** (`INTERVIEW.md`) at the end: headline findings,
   likely questions with answers, and a 2-minute walkthrough.

**Why:** Senior roles both pay more and list more skills, so without an
experience control "skill X pays more" could just mean "senior roles pay
more". City has the same effect (Bengaluru/Mumbai pay more). Company-type
labels turn the original hypothesis into a direct test. No extra API calls
or cost.

### D18: Cleaning rules, Phase 3 (2026-09-29)
Implemented in `cleaning/clean.py`, which writes table `postings_clean` (raw
`postings` untouched; re-run with `python -m cleaning.clean`).

**User decisions:**
- **Posting age:** the main salary analysis uses postings no more than 365
  days old when last seen (`posted_within_1y`); a robustness check re-runs
  it with all ages. Reason: 102 of 180 salaried DA postings were over a year
  old (back to 2019), mostly from recruitment agencies with never-expiring ads.
- **Salary units:** yearly midpoint of the advertised range. Below ₹10k →
  dropped (9 postings: ₹6, ₹180...). ₹10k–₹1L → treated as monthly ×12
  (12 postings; user chose converting over dropping). ₹1L–₹1Cr → yearly. A
  minimum of 0 = not given. Spot check: 2 of the 12 conversions look wrong
  ("Head of Data Analytics" ₹2.16L, an intern ₹10.8L), so Phase 4 must check
  the results hold without the `monthly_x12` rows.
- **Recruitment agencies:** kept, labelled `Staffing / recruiter`.
- **Company types:** Claude drafted labels for the top 60 companies plus
  company-board companies in `cleaning/company_types.csv`
  (`confidence=low` rows marked PLEASE CHECK for user/Sayak review).
  Types: IT & analytics services, Product / tech, Bank & financial services,
  Consulting, Pharma & healthcare, Other global company, Staffing / recruiter,
  Anonymous; the rest are Unlabelled.

**Standard rules (Claude, stated to user):**
- **Internships** (title contains intern/internship): excluded from the
  salary analysis only, since a stipend isn't a salary.
- **Experience level:** title words first (junior: junior/jr/intern/trainee/
  fresher/graduate/entry-level; mid: Assistant/Deputy Manager, Senior
  Executive, following Indian job grades; senior: senior/sr/lead/principal/
  staff/head/director/VP/manager), else years found next to the word
  "experience" (0–2 junior, 3–5 mid, 6+ senior), else **unspecified**. Not
  guessed as mid, to avoid bias.
- **City:** Bengaluru, Hyderabad, Mumbai (incl. Thane/Navi Mumbai), Pune,
  Chennai, Delhi NCR (Delhi/Gurgaon/Noida/Ghaziabad/Faridabad), Other,
  Unknown. The first city mentioned wins.
- **Company names:** regex aliases (`cleaning/company_aliases.csv`, e.g. 25
  Amazon entity names → Amazon; MNC / "Financial Services" / blank →
  Anonymous), then spelling variants merged (case, "Pvt Ltd", "Inc"...).
  "Global" is NOT stripped: Zeta (Indian fintech) ≠ Zeta Global. 1,978 →
  1,883 companies.
- HTML stripped from company-board descriptions.

**Bugs caught while testing:** pandas NaN treated as truthy (city showed 0
Unknown); lowercase spellings chosen as display names; trailing spaces
("InMobi "); "Senior Executive" wrongly marked senior.

**Findings:**
- Experience strongly drives pay (salaried DA, posted within 1 year):
  junior ₹5.7L (n=9), mid ₹9.7L (n=8), senior ₹20.0L (n=19), unspecified
  ₹10.2L (n=46). Confirms the experience control is essential (D17).
- Salary pool so far: 183 postings (skills known, salary, not intern), of
  which 82 were posted within 1 year. The extra-title run (D16) should
  roughly double this.
- **Big employers rarely list salaries:** 72 of 82 salaried DA postings are
  from unlabelled, mostly smaller employers. Salary findings therefore
  describe smaller companies and startups, not MNCs. Company type is used
  in the demand comparison, not as a salary-regression control.

### D19: The story is about skills; experience is only a control (2026-09-29)
**Raised by Dipayan:** "experience means higher pay" is common knowledge, so
it must not be a headline finding. The project should surface non-obvious,
skill-level insights found in our own data.

**Decision:** Experience and city stay in the salary regression as
**controls** (without them, skill effects are confounded: senior roles list
more skills and pay more), but are reported only as method ("compared at
the same experience level and city"), never as findings.

**Headline angles (all from our own data):**
1. **Expected vs premium skills:** skill demand (share of postings) vs pay
   premium (regression). A 4-quadrant chart, the signature visual.
   Preview: Power BI/Tableau common with no premium; ETL less common with a
   consistently positive premium.
2. **More tools ≠ more pay:** job-type clusters. Preview: BI/dashboard
   jobs list the most tools (~6.5) but have the lowest median pay; the
   business-facing profile lists ~3 skills and pays the most.
3. **Excel gets you in, stakeholder skills move you up:** skill shares by
   level. Excel 62% junior → 35% senior; stakeholder management 36% → 63%.
4. **What job ads hide:** skills buried past the first 500 characters (SQL
   68% vs ~6%); big employers rarely publish salaries.

**Framing rule:** say "found in data I collected", never "nobody knows this".
Every claim is reported with its sample size and uncertainty.

### D20: Phase 4 analysis choices and preview results (2026-09-29, n=82 salaried; re-run after the extra-titles run)
**Choices:**
- Population: Data Analyst postings with skills checked, no internships,
  posted within 1 year (1,083 postings; 82 with salary).
- Salary model: OLS on log(salary), robust HC3 errors, controls for
  experience level (base: unspecified) and city group (Bengaluru / other
  metro / other-unknown; cities grouped because each had only 1–16 salaried
  postings). A skill is estimated only if ≥15 salaried postings have it and
  ≥15 don't; otherwise "not enough data" (Azure, AWS, ML, GenAI, A/B testing).
  Three checks: all ages, without monthly ×12 salaries, without controls.
- Wording: "leans higher/lower pay" = same sign in all four versions;
  "certain" = main-model 95% range excludes zero. "Common" skill = in ≥25%
  of postings.
- **Clustering: K = 6, chosen by Dipayan** (best separation score 0.203 of
  K=2..6; low scores overall are normal, since jobs blend). K-means,
  n_init=20, random_state=42. Types are named automatically from their
  skill profiles so the names survive re-runs.
- Company comparison: labelled types with ≥20 postings only.

**Preview results:**
- No single skill is statistically certain yet. Leans higher pay in all 4
  versions: SQL (+21%), stakeholder mgmt (+33%), communication (+37%),
  statistics (+39%), ETL (+22%), Power BI (+15%). Leans lower: Excel
  (−14%), Tableau (−36%). Python: unclear. Monthly ×12 check passed (no
  direction changed).
- **Job types (certain):** at the same experience level and city, the
  business-facing type (~2.8 skills listed) pays +89% (95% range +20% to
  +196%, only 10 salaried postings) vs the BI/dashboard type (~6.5 skills
  listed). The few-skills-listed type pays −37% (−60% to −2%). BI/dashboard
  and business-facing have similar senior shares (39% vs 38%).
- **Hypothesis not supported:** IT services list 4.3 skills per posting
  (the average; fewer than pharma 5.1 and staffing 5.2), and the "SQL + one
  viz tool + communication" pattern is 20% at IT services vs 22% at product
  companies (only 23 product postings).
- **Unexpected cloud split:** Azure is asked for by IT services (41%) but
  rarely by banks (4%); AWS by pharma (61%). Banks rank stakeholder mgmt
  highest (76%).

Outputs: `python -m analysis.run_all` → `results/*.csv` + `meta.json`
(aggregates only, safe to publish).

### D21: Dashboard (Phase 5), built on preview data (2026-09-29)
**Decision:** Streamlit + Plotly dashboard (`dashboard/app.py`) with 11 pages:
Overview, Skills, Salary, 6 job types, Cities, Companies & industries,
Fresher reality, AI/work mode/education, Market trends, Job market explorer,
About & method. Built today on preview data; it updates automatically after
each `python -m analysis.rebuild`. Features chosen from Dipayan's reference
PDF (`Data_Analyst_Job_Market_Dashboard_Features.pdf`), except
job-description keywords (Adzuna snippets are mostly company intro text,
so the keywords would be meaningless).

**Extra data for the PDF's features:** one-off `--extra-tags` run (45 Adzuna
calls, 2026-09-29) tagging Data Analyst postings for work mode (remote/WFH,
hybrid), education (degree, Master's/MBA) and AI terms (ChatGPT/OpenAI,
Copilot, automation, "artificial intelligence"), using the same full-text
approach as skills (D9). Stored as tags, kept out of the 14-skill analyses.
Result: remote/WFH 14%, hybrid 14%, not stated 78%; automation 40%, GenAI 8%,
ChatGPT 2%; degree 55%, Master's/MBA 29%.

**Populations:** skill views use Data Analyst postings (skills known). City
pay, title mix and companies use all analyst roles (more salaried postings)
and say so on the chart. City pay is shown only with ≥10 salaried postings.

**Explorer table:** `results/explorer.csv` is **de-identified**: one row per
Data Analyst posting with only derived attributes (city, level, company
type, job type, salary rounded to ₹0.5L, work-mode flags, skill flags), and
no IDs, titles, company names, text or links, shuffled. Within D15's "no raw
listings published" rule; Adzuna is credited on every page.

**Chart rules (dataviz guidance):** reference colour-blind-validated palette
(the validator script couldn't run: Node.js not installed); pies only for
part-to-whole with ≤6 slices, % inside plus a legend naming every slice;
single-colour bars; one fixed colour per job type everywhere (colour follows
the entity); sequential blue heatmaps; a "Show the numbers" table under
every chart; money in ₹ lakh.

**Found while testing every page:** clipped bar labels, clipped pie and
scatter labels, overlapping scatter labels, heatmap keys in decimals, job-type
colours changing when filtering, "up" arrows implying growth, date axis in
hours, and a stale-data bug from running steps out of order →
`python -m analysis.rebuild` now runs database → cleaning → analysis in order.

### D22: Publish the dashboard now from a separate, public, dashboard-only repo (2026-09-29)
**Asked by Dipayan:** share the dashboard with friends and colleagues now,
not after the 14 Oct freeze.

**Decision:** A second repository, `workforce-ai-dashboard`
(~/Desktop/workforce-ai-dashboard, **public**), containing only
`dashboard/app.py`, `results/` (aggregated files + the de-identified explorer
table), `.streamlit/config.toml`, a short README and `requirements.txt`
(pandas, streamlit, plotly). Fresh git history, so no raw data was ever in it.
Hosted on **Streamlit Community Cloud**. The main project repo (raw Adzuna
data) stays **private**. `./publish_dashboard.sh` copies new results over
after each rebuild; then commit and push that repo and the site updates.

**Payment check (2026-09-29):** Streamlit Community Cloud is free for public
apps with no credit card; sign-in is with GitHub. Limits: apps sleep after
~12 h without visitors (~30 s wake-up), ~1 GB memory. Rule stands: if it
ever asks for a card, don't add one.

**Rejected:** Power BI "publish to web" (needs a work/school account and a
paid licence: payment risk). Tableau Public is free but would mean
rebuilding every chart by hand.

**Verified:** all 11 pages execute without errors from the standalone folder
(Streamlit AppTest); the explorer table has no identifiers.

### D23: Dark "developer tool" Streamlit restyle: dropped (2026-09-29)
A dark restyle after a first reference screenshot was written but never
shipped: Dipayan then chose a lighter, premium reference (D24). The Streamlit
app stays as it was (D21) and serves as the backup dashboard.

### D24: Premium website on GitHub Pages (2026-09-29)
**Asked by Dipayan:** a premium-looking site like his reference (light
"frosted glass" dashboard), with a proper home page explaining what we do and
why, separate pages instead of one long list, a strong hero picture, and
animations. No paid domain.

**Decision:** A custom static website (`site/`: 8 HTML pages, one CSS file,
one JS file, Apache ECharts from jsDelivr), published to the PUBLIC repo's
`docs/` folder and served free by **GitHub Pages** at
`https://dipayan8k.github.io/workforce-ai-dashboard/`. No domain purchase,
no card, and it doesn't sleep (unlike Streamlit Community Cloud). Streamlit
stays online as a backup. `./publish_dashboard.sh` rebuilds
`docs/data/data.json` from `results/` (aggregates + de-identified explorer
table only) and copies the site.

**Pages:** Home (hero, what we do, how it works in 5 steps, key findings, CTA)
· Skills · Salary · Job types · Cities & companies · Market (fresher reality,
AI/work mode/education, trends) · Explorer · About.

**Hero picture:** an animated map of India's analyst job hubs **built from our
data** (dot size = postings, pulsing rings, flowing links), instead of a
stock photo. City dots only, **no country outline**: free boundary datasets
often draw India's borders differently from the official map.

**Motion (off under prefers-reduced-motion):** one hero entrance sequence,
count-up numbers, cards revealing on scroll, charts drawing when they come
into view.

**Design:** light glass cards on a soft grey canvas, Geist typeface, one green
accent for navigation and actions. Chart colours = the dataviz reference
palette: the validator passes (worst adjacent CVD ΔE 9.1) with a contrast
warning for the lighter slots, so every chart has visible value labels or a
"Show the numbers" table. Checked at 1440px and 375px (no horizontal scroll).

**Found in testing and fixed:** overlapping map labels, clipped map label on
phones, oversized map gaps on phones, legend overlapping chart labels, axis
title clipping, confidence ranges running off the salary chart, dark-on-dark
heatmap text, donut legends overlapping in narrow cards, crowded axis ticks.

### D25: Monospace font tried, rolled back (2026-09-29)
JetBrains Mono (for a "technical" look, after a reference screenshot) was
tried on the website and rolled back at Dipayan's request. Geist stays.
Kept from that session: a smaller, bolder hero headline with an
ink-to-forest-green gradient.

### D26: Dark mode, dark by default (2026-09-29)
**Decision:** The website opens in **dark mode for every new visitor**
(Dipayan's choice: it looks best). A header switch cycles
Dark → Light → Auto (Auto follows the device, e.g. dark after sunset),
remembered per visitor in their browser (localStorage). A one-line script
in each page's head applies the choice before the page draws, so there's no
white flash. Charts redraw with the dataviz palette's dark-mode steps and a
dark sequential ramp. Tested: fresh visitor on a light device lands in dark;
Dark → Auto → Light switching works with no errors.

### D27: Resume analyzer (2026-09-30)
**Decision:** A new website page, "Analyze your resume" (resume.html, in the
menu and linked from the home page). A visitor adds a PDF or pastes text;
it's read **in their browser only** (pdf.js from cdnjs), never uploaded or
stored. **No paid AI:** skills are found by keyword lists for our 14 skills
(e.g. "MySQL" → SQL, "DAX" → Power BI), and the visitor can tap skills on or
off to fix mistakes (or skip the resume and just tap).
The match uses our de-identified Data Analyst jobs (those naming ≥1 of the 14
skills): jobs fully matched, jobs one skill away, fit per job type, median
advertised pay of matched jobs (shown only with 5+ salaried ads). Missing
skills are ranked by **"jobs it opens"**: jobs where it's the only missing
skill (High ≥ 5% of jobs, Medium ≥ 1.5%), with demand share and pay signal.
"Towards senior roles" lists missing skills that rise from junior to senior.
**Learning time** is a rough average in months at ~1 hr/day, chosen by the
team (Dipayan's choice) and labelled as guidance, not data.

### D28: Cinematic redesign (2026-09-30)
**Decision:** Dipayan shared a screen recording of a premium fintech site
(cred.club) as the look to aim for. We copied the **style**, not the site:
none of its 3D videos, logo, name or text are used (they're its own
property, and a look-alike could read as impersonation).
- Pure black canvas, big bold serif headlines (Fraunces, free on Google
  Fonts) with Geist body text, hairline cards, letter-spaced capital labels.
- ☰ full-screen menu instead of a row of links; a floating "analyze your
  resume" box on every page.
- Home page (Dipayan's choice: home cinematic, other pages matched):
  a hero **corridor whose columns are our 14 skill-demand bars**, drawn in
  canvas with a slow camera drift and warm light between columns; a story
  paragraph that lights up word by word on scroll; a **ring of the 14 skills**
  that turns on scroll; page cards that slide sideways as you scroll
  (a swipeable row on phones); the city map; findings; a code-drawn
  "door of light" for the resume check; a privacy promise.
- Every number shown comes from our results (e.g. "92% of jobs that name a
  city are in six metros" is computed, not typed). Light mode and reduced
  motion still work; the hero pauses its animation when off screen.

### D29: Skill map as bars + line (2026-09-30)
Dipayan found the scatter "skill map" hard to read and asked for a line
chart. A line alone would imply an order between unrelated skills, so the
chart became a combo: **bars** = share of Data Analyst jobs asking for the
skill (sorted, most common first), **line with labelled dots** = advertised
pay difference, dots coloured by pay signal (same data as before).

### D30: Skill map simplified to a ranking (2026-09-30)
The combo was still too complex for a general audience ("a middle-aged
visitor should get it at a glance"). Now: one sentence ("Communication is the
most asked-for skill… then SQL… Learn these first") plus a ranked bar chart,
#1 at the top, top 3 highlighted, each bar labelled "65% · tends to pay more /
tends to pay less / no clear pay difference". "Tends to" because no pay effect
is statistically certain yet. Exact numbers stay in "Show the numbers" and on
the Salary page.
Also removed (Dipayan: too complicated): the 14×14 skill co-occurrence heatmap.
"Skills that come together" (top pairs/triples) already tells the same story simply.

### D31: Floating resume box removed (2026-09-30)
Dipayan asked to remove the bottom-right "analyze your resume" box from every
page (it covered charts and text). The resume check is still reachable from
the ☰ menu, the home-page card and the door-of-light section.

### D32: Extra-titles run done; hybrid population; findings re-checked (2026-10-01)
**Collection:** extra-titles skill tagging split over two days (estimate for
all 7 titles was ~217 calls, too close to the 240 cap): 30 Sep 129 calls
(business intelligence, power bi, product analyst, insights analyst), 1 Oct
61 calls (reporting analyst, bi analyst, mis analyst). New `--titles` flag.
**Decision (Dipayan: hybrid):** skill demand, job types, junior-vs-senior,
explorer and the resume check use **Data Analyst postings only** (1,083), as
the site says. The **salary models use the bigger pool** (Data Analyst + the
7 close titles, 2,168 postings, **158 salaried**, was 82) with job title as a
control. Job-type pay: types are defined on Data Analyst postings, then the
related postings are sorted into the same types (`clusters.type_all`).
**What changed (honest corrections):**
- "Business-facing jobs pay +89% more than BI/dashboard jobs" (n=10) did NOT
  survive: now -12%, 95% range -44% to +39%. The finding is restated as "more
  tools doesn't mean more pay": ~7 vs ~3 skills listed, no clear pay
  difference. Every job type is within ±20% of BI/dashboard.
- Skills that lean higher pay (same sign in all 4 versions): SQL, Python,
  Tableau, Statistics, Azure. Communication and Stakeholder mgmt are now
  unclear. Excel and ETL lean lower. Still none statistically certain.
- Unchanged: Excel 62% junior → 35% senior; stakeholder 36% → 63%; pharma
  asks for AWS in 61% of jobs.
Site/dashboard finding text is now computed from the data so it can't go stale.

## Week 1 observations (run 2026-09-27, 5,598 Adzuna + 73 company-board postings)
- **Adzuna India does not predict salaries:** all 813 postings with a salary
  (15%) are employer-advertised. So D5 costs nothing, but the salary sample is
  small: 184 of the 1,151 "data analyst" postings list a salary.
- **Old postings are still "open":** `created` dates go back to 2019 (median
  2026-08-21). We need a staleness rule (Phase 3).
- **Salary outliers:** advertised midpoints range from ₹78 to ₹50 lakh/yr, so
  some are probably monthly figures or typos. We need a salary-cleaning rule.
- **Company names need merging:** e.g. "Amazon" and "ADCI - Karnataka" (an
  Amazon entity) are listed separately. 1,827 distinct names.
- **Descriptions are exactly 500 characters** (truncation confirmed, D1).
- 37% of postings only say "India" with no city or state.

## Run 2 observations (first scheduled run, Mon 2026-09-28 09:08 IST)
- All three sources OK: 5,541 Adzuna postings (127 calls), 1,267 skill tags
  (34 calls), 73 company-board postings. 161 Adzuna calls in total, under
  the 250/day limit.
- Only ~14 hours after run 1: 5,347 postings still open, 324 disappeared,
  267 new. Run 1 (Sunday) is treated as a "week 0" baseline for trends,
  because of the uneven gap.
- First skill-demand numbers (293 Data Analyst postings created in the last
  10 days, so preliminary): communication 66%, SQL 63%, stakeholder 59%,
  Python 45%, Excel 39%, statistics 36%, Tableau 32%, Power BI 26%, ETL 18%,
  Azure 15%, AWS 11%, generative AI 10%, machine learning 10%, A/B testing 4%.
- Only 21 of those 293 list a salary, far too few for regression. The
  backfill (all ~1,190 open DA postings) is needed before any salary analysis.

## Skill backfill observations (Tue 2026-09-29, run 2026-09-29_1210Z)
- 114 Adzuna calls (estimate was ~90), no truncation, 5,297 skill tags.
- Data Analyst postings with known skills: 293 → 1,253; with a salary: 21 → 186.
- 145 tags point to postings created after Monday's collection. They'll
  join once the next scheduled run collects those postings.
- **First raw salary comparison** (median advertised salary, postings
  with vs without each skill; 180 postings within a temporary ₹1L–₹1Cr
  sanity band; overall median ₹7.5L): AWS +93% (n=16), SQL +50% (n=137),
  machine learning +50% (n=22), Azure +47% (n=15), stakeholder +43% (n=75),
  ETL +40% (n=26), communication +19%, Python +14%, statistics +10%,
  Power BI 0%, Tableau 0%, **Excel −22%** (n=92).
- **Not yet trustworthy:** no control for experience or city (D17), small
  samples for AWS/Azure/ML, uncleaned salaries. Plausible confounder: Excel
  is common in junior/MIS roles, which pay less. This is exactly why the
  regression needs experience controls.

## Open questions (decide once real data arrives)
- **Week definition for trends:** a posting's `created` date, or the run that
  first saw it?
- **In-scope titles:** which of the broad titles count as "Data Analyst"
  for the headline analysis? (Phase 3)

### D33: Collection frozen early (2026-10-04)
**Decision (Dipayan):** freeze now instead of after 14 Oct. Final data: runs of
27 Sep – 1 Oct 2026 (8 raw snapshots), already analysed (D32). Done by Claude:
deleted `.github/workflows/weekly_collect.yml` (so the Mon 5 Oct run cannot
start) and deleted `.env`. Checked before deleting: the keys never appeared in
any file or commit of either repo. Left for Dipayan: delete the GitHub Secrets
ADZUNA_APP_ID / ADZUNA_APP_KEY; optionally ask Adzuna to close the account.
The collector code stays (for reference/interviews) but cannot run without keys.
