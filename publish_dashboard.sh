#!/bin/bash
# Publishes ONLY aggregated results into the separate, PUBLIC repo
# (~/Desktop/workforce-ai-dashboard). Raw Adzuna data never goes there
# (DECISIONS.md, D15/D21/D22/D24). It copies:
#   1. the premium website -> docs/   (GitHub Pages serves this folder)
#   2. the Streamlit backup dashboard -> dashboard/, results/
#
# Usage (from this project folder, after `python -m analysis.rebuild`):
#     ./publish_dashboard.sh
# Then in GitHub Desktop, switch to "workforce-ai-dashboard", commit, push.
set -e
DEST="$HOME/Desktop/workforce-ai-dashboard"

# 1. website
mkdir -p "$DEST/docs/assets" "$DEST/docs/data"
cp site/*.html "$DEST/docs/"
cp site/assets/* "$DEST/docs/assets/"
.venv/bin/python site/build_data.py "$DEST/docs/data/data.json"
touch "$DEST/docs/.nojekyll"   # serve files as-is (no Jekyll processing)

# 2. Streamlit backup
mkdir -p "$DEST/dashboard" "$DEST/results" "$DEST/.streamlit"
cp dashboard/app.py "$DEST/dashboard/app.py"
cp .streamlit/config.toml "$DEST/.streamlit/config.toml"
rm -f "$DEST/results/"*
cp results/*.csv results/*.json "$DEST/results/"
grep -E "^(pandas|streamlit|plotly)==" requirements.txt > "$DEST/requirements.txt"

echo "Published website ($(ls "$DEST/docs"/*.html | wc -l | tr -d ' ') pages) + backup dashboard ($(ls "$DEST/results" | wc -l | tr -d ' ') result files) to $DEST"
