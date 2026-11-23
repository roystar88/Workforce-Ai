#!/bin/bash
# Double-click this file to open the WorkForce AI dashboard in your browser.
# Keep this Terminal window open while you use the dashboard; close it to stop.
cd "$(dirname "$0")"
echo "Starting the WorkForce AI dashboard... (keep this window open)"
.venv/bin/streamlit run dashboard/app.py --server.port 8501
