.PHONY: setup db migrate seed dev backend frontend test eval

EVAL_DB_URL = $(shell cd backend && uv run python -c 'from app.config import eval_database_url; print(eval_database_url())')

setup:            ## install backend + frontend dependencies, create .env
	cd backend && uv sync
	cd frontend && pnpm install
	test -f .env || cp .env.example .env

db:               ## create the 'mira' role (password from DATABASE_URL) and the app + eval databases
	cd backend && uv run python -m seed.create_db

migrate:          ## apply migrations to both databases
	cd backend && uv run alembic upgrade head
	cd backend && DATABASE_URL=$(EVAL_DB_URL) uv run alembic upgrade head

seed:             ## (re)load the fictional catalog and inventory calendar into the app database
	cd backend && uv run python -m seed.seed

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

dev:              ## run API (:8000) and UI (:5173) together
	$(MAKE) -j2 backend frontend

test:             ## unit + integration tests (uses mira_eval, no LLM calls)
	cd backend && uv run pytest -q

eval:             ## run the scripted conversations against the real model (uses mira_eval)
	cd backend && uv run python -m evals.runner $(ARGS)
