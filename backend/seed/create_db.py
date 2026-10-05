"""Create the DB role and both databases (mira, mira_eval) from DATABASE_URL in .env, via psql as your OS user.

Run: make db   (idempotent: existing role/databases are left as they are)
"""

import subprocess

from sqlalchemy.engine import make_url

from app.config import EVAL_DATABASE, get_settings


def psql(sql: str, **variables: str) -> str:
    args = ["psql", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-Atq"]
    for k, v in variables.items():
        args += ["-v", f"{k}={v}"]
    return subprocess.run(args, input=sql, text=True, capture_output=True, check=True).stdout.strip()


def main() -> None:
    url = make_url(get_settings().database_url)
    role, password = url.username, url.password
    if not role or not password:
        raise SystemExit(
            "DATABASE_URL in .env must include a user and password, e.g. postgresql+asyncpg://rakesh:pass1234@localhost:5432/mira"
        )

    if psql("SELECT 1 FROM pg_roles WHERE rolname = :'role'", role=role):
        print(f"role {role} exists")
    else:
        psql("CREATE ROLE :\"role\" LOGIN PASSWORD :'pw'", role=role, pw=password)
        print(f"created role {role}")

    for db in (url.database, EVAL_DATABASE):
        if psql("SELECT 1 FROM pg_database WHERE datname = :'db'", db=db):
            print(f"database {db} exists")
        else:
            psql('CREATE DATABASE :"db" OWNER :"role"', db=db, role=role)
            print(f"created database {db} owned by {role}")


if __name__ == "__main__":
    main()
