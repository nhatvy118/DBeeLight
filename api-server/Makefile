.PHONY: help migrate-up migrate-down run

# Requires: golang-migrate CLI (`migrate`)
# Usage:
#   make migrate-up DB_URL=postgres://...
#   make migrate-down DB_URL=postgres://...
#

# Default DB URL used by migrate-* targets when DB_URL / DATABASE_URL aren't set
# in the environment. NOT exported globally — otherwise it would override
# DB_URL/DATABASE_URL loaded from api-server/.env when running the server.
DEFAULT_DB_URL = postgres://pila_vyhuynh:postgres@localhost:5432/mcp-api-server?sslmode=disable

help:
	@echo "Targets:"
	@echo "  run                        (start FastAPI server via uv)"
	@echo "  migrate-up / migrate-down  (metadata Postgres via golang-migrate)"
	@echo ""
	@echo "Vars:"
	@echo "  DB_URL (or DATABASE_URL)"

run:
	. .venv/bin/activate && uv run api-server

migrate-up:
	@DB=$${DB_URL:-$${DATABASE_URL:-$(DEFAULT_DB_URL)}}; \
	if [ -z "$$DB" ]; then echo "Missing DB_URL or DATABASE_URL"; exit 1; fi; \
	if ! command -v migrate >/dev/null 2>&1; then echo "Missing 'migrate' CLI. Install golang-migrate and retry."; exit 1; fi; \
	migrate -path migrations_pg -database "$$DB" -verbose up

migrate-down:
	@DB=$${DB_URL:-$${DATABASE_URL:-$(DEFAULT_DB_URL)}}; \
	if [ -z "$$DB" ]; then echo "Missing DB_URL or DATABASE_URL"; exit 1; fi; \
	if ! command -v migrate >/dev/null 2>&1; then echo "Missing 'migrate' CLI. Install golang-migrate and retry."; exit 1; fi; \
	migrate -path migrations_pg -database "$$DB" -verbose down 1
