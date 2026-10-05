import os

from app.config import eval_database_url

# Tests run against the eval database with a frozen "today" (Tue 6 Oct 2026).
os.environ["DATABASE_URL"] = eval_database_url()
os.environ["MIRA_TODAY"] = "2026-10-06"
