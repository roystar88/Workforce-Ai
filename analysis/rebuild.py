"""
Rebuild everything, in the right order, with one command:

    python -m analysis.rebuild

  1. database  - load every data/raw/ snapshot into SQLite
  2. cleaning  - write postings_clean
  3. analysis  - write results/ (what the dashboard reads)

Running these out of order once left the dashboard with stale numbers,
so always use this.
"""

from analysis import run_all
from cleaning import clean
from database import build_db

if __name__ == "__main__":
    build_db.build()
    clean.report(clean.build())
    run_all.main()
