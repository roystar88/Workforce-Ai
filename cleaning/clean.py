"""
Phase 3: turn raw postings into clean, analysis-ready rows.

Usage (after `python -m database.build_db`):

    python -m cleaning.clean

Reads the `postings` table, applies the cleaning rules below, and writes a
new table `postings_clean` into the same database (one row per posting).
The raw `postings` table is never modified, so every rule can be changed and
re-run at any time.

Every rule here was decided on purpose. See DECISIONS.md, D18, for the why.
The rules that people are most likely to want to tweak live in CSV files
next to this script:
    company_aliases.csv  - which raw company names are the same company
    company_types.csv    - hand-labelled company type for the top companies
"""

import html
import re
import sqlite3
from pathlib import Path

import pandas as pd

from database.build_db import DB_PATH

HERE = Path(__file__).parent


# --- Company -----------------------------------------------------------------

# Words that don't change which company it is: "Infosys Limited" = "Infosys".
# ("global" is deliberately NOT here: Zeta and Zeta Global are different companies.)
_COMPANY_NOISE = re.compile(
    r"\b(private|pvt|limited|ltd|llp|inc|india|corporation|corp|co|company|group|the)\b"
)


def company_key(name: str) -> str:
    """'Genpact' and 'genpact', 'Cigna Group' and 'The Cigna Group' -> the same key."""
    name = re.sub(r"[.,&()'\-]", " ", name.lower())
    return " ".join(_COMPANY_NOISE.sub(" ", name).split())


def clean_companies(raw: pd.Series) -> pd.Series:
    """Map every raw company name to one clean name."""
    aliases = pd.read_csv(HERE / "company_aliases.csv")

    def apply_alias(name):
        if name is None or pd.isna(name) or not str(name).strip():
            return "Anonymous"
        for pattern, company in zip(aliases["pattern"], aliases["company"]):
            if re.search(pattern, name):
                return company
        return name.strip()

    named = raw.map(apply_alias)
    # Group spelling variants by key; show each group under its most common
    # spelling, preferring properly capitalised names ("Paytm" over "paytm").
    keys = named.map(company_key)
    display = named.groupby(keys).agg(
        lambda s: max(s.value_counts().items(), key=lambda kv: (not kv[0].islower(), kv[1]))[0])
    return keys.map(display)


def company_types(companies: pd.Series) -> pd.DataFrame:
    """Look up the hand-labelled type; everything unlabelled is 'Unlabelled'."""
    labels = pd.read_csv(HERE / "company_types.csv")
    lookup = labels.set_index("company")
    out = pd.DataFrame(index=companies.index)
    out["company_type"] = companies.map(lookup["company_type"]).fillna("Unlabelled")
    out["company_type_confidence"] = companies.map(lookup["confidence"])
    out.loc[companies == "Anonymous", "company_type"] = "Anonymous"
    return out


# --- Salary --------------------------------------------------------------------

def clean_salary(salary_min, salary_max) -> tuple[float | None, str]:
    """
    Returns (yearly salary in INR, which rule was applied).

    We use the MIDDLE of the advertised range. Rules (D18):
      below ₹10k      -> dropped (₹6, ₹180... typos or other units, can't be trusted)
      ₹10k to ₹1L     -> treated as MONTHLY, multiplied by 12 (user decision)
      ₹1L to ₹1Cr     -> taken as yearly
      above ₹1Cr      -> dropped (none seen so far; just a safety net)
    A minimum of 0 means "not given", so only the maximum is used.
    """
    lo = salary_min if salary_min and salary_min > 0 else None
    hi = salary_max if salary_max and salary_max > 0 else None
    if lo is None and hi is None:
        return None, "no_salary"
    mid = ((lo or hi) + (hi or lo)) / 2
    if mid < 10_000:
        return None, "dropped_implausible"
    if mid < 100_000:
        return mid * 12, "monthly_x12"
    if mid > 10_000_000:
        return None, "dropped_implausible"
    return mid, "annual"


# --- Experience ------------------------------------------------------------------

# Indian job grades: Assistant/Deputy Manager and Senior Executive are MID level.
_MID_TITLE = re.compile(r"\b(assistant|asst|deputy)\.?\s+manager\b|\bsenior\s+executive\b", re.I)
_SENIOR_TITLE = re.compile(r"\b(senior|sr|lead|principal|staff|head|director|vp|avp|manager)\b", re.I)
_JUNIOR_TITLE = re.compile(r"\b(junior|jr|intern|internship|trainee|fresher|freshers|graduate|entry[- ]level)\b", re.I)
# "3-5 years of experience", "4+ yrs exp", "experience: 2 to 4 years"...
# Requiring the word experience/exp nearby avoids "a company with 200 years of history".
_YEARS = [
    re.compile(r"(\d{1,2})\s*(?:\+|-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:\w+\s+)?(?:experience|exp)\b", re.I),
    re.compile(r"(?:experience|exp)\s*(?:of|:|-)?\s*(\d{1,2})\s*(?:\+|-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years?|yrs?)", re.I),
]


def years_required(text: str) -> int | None:
    for pattern in _YEARS:
        m = pattern.search(text)
        if m and int(m.group(1)) <= 25:
            return int(m.group(1))  # the lower bound, e.g. 3 in "3-5 years"
    return None


def experience_level(title: str, text: str) -> tuple[str, int | None]:
    """
    junior / mid / senior / unspecified. The title wins; otherwise years:
    0-2 junior, 3-5 mid, 6+ senior. 'unspecified' when there's no signal at
    all. We don't guess 'mid' for those, because guessing could bias results.
    """
    years = years_required(f"{title} {text}")
    if _JUNIOR_TITLE.search(title):
        return "junior", years
    if _MID_TITLE.search(title):
        return "mid", years
    if _SENIOR_TITLE.search(title):
        return "senior", years
    if years is not None:
        return ("junior" if years <= 2 else "mid" if years <= 5 else "senior"), years
    return "unspecified", years


# --- City -------------------------------------------------------------------------

_CITIES = {  # checked in the text; the city mentioned FIRST wins
    "Bengaluru": r"bangalore|bengaluru|\bblr\b",
    "Hyderabad": r"hyderabad|secunderabad",
    "Mumbai": r"mumbai|thane",
    "Pune": r"\bpune\b",
    "Chennai": r"chennai",
    "Delhi NCR": r"delhi|gurgaon|gurugram|noida|ghaziabad|faridabad",
}


def clean_city(city, location_text) -> str:
    # pandas gives missing values as NaN, which Python treats as TRUE, so
    # convert them to "" explicitly (a real bug caught in testing).
    city = "" if pd.isna(city) else city
    location_text = "" if pd.isna(location_text) else location_text
    text = f"{city} | {location_text}".lower()
    hits = [(m.start(), name) for name, pat in _CITIES.items() if (m := re.search(pat, text))]
    if hits:
        return min(hits)[1]
    return "Other" if city else "Unknown"


# --- Text ---------------------------------------------------------------------------

def strip_html(text) -> str:
    """Company-board descriptions are HTML; keep just the words."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(html.unescape(text).split())


# --- Build postings_clean -----------------------------------------------------------

def build() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT p.*, l.first_seen, l.last_seen, l.runs_seen,
               (SELECT GROUP_CONCAT(search_term, '|') FROM posting_search_terms t
                 WHERE t.posting_id = p.posting_id)                AS search_terms,
               p.posting_id IN (SELECT posting_id FROM skill_tagged_postings) AS skills_checked
        FROM postings p JOIN posting_lifespan l USING (posting_id)
    """, con)

    out = pd.DataFrame({"posting_id": df["posting_id"], "source": df["source"], "title": df["title"]})
    out["company_raw"] = df["company_name"]
    out["company"] = clean_companies(df["company_name"])
    out = out.join(company_types(out["company"]))

    out["city"] = [clean_city(c, l) for c, l in zip(df["city"], df["location_text"])]
    out["description_text"] = [strip_html(d) for d in df["description"]]
    levels = [experience_level(t, d) for t, d in zip(df["title"], out["description_text"])]
    out["experience_level"] = [lvl for lvl, _ in levels]
    out["years_min"] = pd.array([yrs for _, yrs in levels], dtype="Int64")
    out["is_internship"] = df["title"].str.contains(r"\bintern(?:ship)?s?\b", case=False, regex=True)

    salaries = [clean_salary(lo, hi) for lo, hi in zip(df["salary_min"], df["salary_max"])]
    out["salary_annual"] = [s for s, _ in salaries]
    out["salary_rule"] = [rule for _, rule in salaries]

    # Age = how old the posting was when we LAST saw it open.
    created = pd.to_datetime(df["created_at"], utc=True, format="ISO8601")
    last_seen = pd.to_datetime(df["last_seen"], utc=True, format="ISO8601")
    out["created_at"] = df["created_at"]
    out["last_seen"] = df["last_seen"]
    out["runs_seen"] = df["runs_seen"]
    out["age_days"] = (last_seen - created).dt.days.clip(lower=0)
    out["posted_within_1y"] = out["age_days"] <= 365          # D18: main salary analysis window
    out["search_terms"] = df["search_terms"]
    out["skills_checked"] = df["skills_checked"].astype(bool)

    out.to_sql("postings_clean", con, if_exists="replace", index=False)
    con.close()
    return out


def report(out: pd.DataFrame) -> None:
    """Print what each rule did, so nothing happens silently."""
    print(f"postings_clean: {len(out):,} rows\n")
    print("salary rules:\n", out["salary_rule"].value_counts().to_string(), "\n")
    print("experience level:\n", out["experience_level"].value_counts().to_string(), "\n")
    print("city:\n", out["city"].value_counts().to_string(), "\n")
    print("company type:\n", out["company_type"].value_counts().to_string(), "\n")
    print(f"distinct companies: raw {out['company_raw'].nunique():,} -> clean {out['company'].nunique():,}")
    reg = out[out.skills_checked & out.salary_annual.notna() & ~out.is_internship]
    print(f"salary-analysis pool (skills known, salary, not intern): {len(reg)} "
          f"| posted within 1 year: {int(reg.posted_within_1y.sum())}")


if __name__ == "__main__":
    report(build())
