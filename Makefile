.PHONY: up down build logs db-shell redis-shell migrate test lint cycle

# ── Docker ──
up:
	docker compose up -d
	@echo "Bahamut.AI running at http://localhost:3000 (frontend) and http://localhost:8000 (API)"

down:
	docker compose down

build:
	docker compose build --no-cache

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker

logs-beat:
	docker compose logs -f beat

# ── Database ──
db-shell:
	docker compose exec postgres psql -U bahamut -d bahamut

redis-shell:
	docker compose exec redis redis-cli

migrate:
	docker compose exec api alembic upgrade head

migrate-new:
	docker compose exec api alembic revision --autogenerate -m "$(msg)"

# ── Development ──
test:
	docker compose exec api python -m pytest tests/ -v

lint:
	docker compose exec api python -m ruff check bahamut/

# ── Signal Cycle (manual trigger) ──
cycle:
	docker compose exec worker celery -A bahamut.celery_app call bahamut.agents.tasks.run_all_signal_cycles

cycle-single:
	docker compose exec worker celery -A bahamut.celery_app call bahamut.agents.tasks.run_single_cycle --args='["EURUSD","fx","4H","BALANCED"]'

# ── Health ──
health:
	@curl -s http://localhost:8000/health | python -m json.tool

# ── Reset ──
reset:
	docker compose down -v
	docker compose up -d
	@echo "Full reset complete. Database wiped and recreated."
