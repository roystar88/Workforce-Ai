"""
One shared, polite HTTP client for every source.

Why not just call requests.get() everywhere? Because networks fail. This
session automatically RETRIES when a server says "too many requests" (429) or
has a temporary error (5xx), waiting longer each time (2s, 4s, 8s, ...).
That's called exponential backoff: it gives the server room to recover
instead of hammering it.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Identify ourselves honestly instead of pretending to be a browser.
USER_AGENT = "WorkForceAI-research/0.1 (personal job-market research project)"


def make_session() -> requests.Session:
    retry = Retry(
        total=4,                                   # up to 4 retries per request
        backoff_factor=2,                          # wait 2s, 4s, 8s, 16s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,           # obey the server if it says "wait N seconds"
    )
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
