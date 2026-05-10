.PHONY: help migrate-up migrate-down

# Requires: golang-migrate CLI (`migrate`)
# Usage:
#   make migrate-up DB_URL=postgres://...
#   make migrate-down DB_URL=postgres://...
#

# export DATABASE_URL ?= postgres://pila_vyhuynh:postgres@localhost:5432/mcp-api-server?sslmode=disable
export DATABASE_URL = postgres://postgres:postgres@localhost:5432/database_app?sslmode=disable
help:
	@echo "Targets:"
	@echo "  migrate-up / migrate-down  (metadata Postgres via golang-migrate)"
	@echo ""
	@echo "Vars:"
	@echo "  DB_URL (or DATABASE_URL)"

migrate-up:
	@DB=$${DB_URL:-$${DATABASE_URL}}; \
	if [ -z "$$DB" ]; then echo "Missing DB_URL or DATABASE_URL"; exit 1; fi; \
	if ! command -v migrate >/dev/null 2>&1; then echo "Missing 'migrate' CLI. Install golang-migrate and retry."; exit 1; fi; \
	migrate -path migrations_pg -database "$$DB" -verbose up

migrate-down:
	@DB=$${DB_URL:-$${DATABASE_URL}}; \
	if [ -z "$$DB" ]; then echo "Missing DB_URL or DATABASE_URL"; exit 1; fi; \
	if ! command -v migrate >/dev/null 2>&1; then echo "Missing 'migrate' CLI. Install golang-migrate and retry."; exit 1; fi; \
	migrate -path migrations_pg -database "$$DB" -verbose down 1
