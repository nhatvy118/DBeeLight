# DBeeLight Backend — dev helpers
#
# Local (uv):       make install → make migrate → make excel (tab riêng) → make api
# Docker (toàn bộ): make up   /  make down  /  make logs
#
# Biến đọc từ .env. Override khi cần: make api PORT=8000

SHELL := /bin/bash

# --- load .env nếu có ---
ifneq (,$(wildcard .env))
include .env
export
endif

DATABASE_URL ?= postgresql://postgres:postgres@localhost:5432/dbeelight
DATA_ROOT    ?= ./_data
PORT         ?= 5001
EXCEL_PORT   ?= 8931
EXCEL_FILES_PATH ?= $(abspath $(DATA_ROOT))/uploads

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Local (uv):"
	@echo "  make install   - uv sync (cài deps)"
	@echo "  make dirs       - tạo thư mục _data/{uploads,databases,temp_dbs}"
	@echo "  make migrate    - chạy tất cả migrations vào DATABASE_URL"
	@echo "  make excel      - chạy Excel MCP server (port $(EXCEL_PORT)) — tab riêng"
	@echo "  make api        - chạy FastAPI (uvicorn, port $(PORT), --reload)"
	@echo "  make test       - chạy smoke tests"
	@echo ""
	@echo "Docker:"
	@echo "  make up / down / logs / ps"
	@echo "  make up-db      - chỉ postgres + excel-server"
	@echo ""
	@echo "Vars: DATABASE_URL, DATA_ROOT, PORT, EXCEL_PORT, EXCEL_FILES_PATH"

# ---------- Local (uv) ----------
.PHONY: install
install:
	uv sync

.PHONY: dirs
dirs:
	mkdir -p $(DATA_ROOT)/uploads $(DATA_ROOT)/databases $(DATA_ROOT)/temp_dbs

.PHONY: migrate
migrate:
	@for f in migrations/*.sql; do \
		echo ">> $$f"; \
		psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f "$$f" || exit 1; \
	done
	@echo "Migrations done."

.PHONY: excel
excel: dirs
	EXCEL_FILES_PATH=$(EXCEL_FILES_PATH) FASTMCP_PORT=$(EXCEL_PORT) \
		uv run --with "excel-mcp-server>=0.1.8" python -m excel_mcp streamable-http

.PHONY: api
api: dirs
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port $(PORT)
	
# ---------- Docker ----------
.PHONY: up
up:
	docker compose up --build

.PHONY: up-db
up-db:
	docker compose up postgres excel-server

.PHONY: down
down:
	docker compose down

.PHONY: logs
logs:
	docker compose logs -f

.PHONY: ps
ps:
	docker compose ps
