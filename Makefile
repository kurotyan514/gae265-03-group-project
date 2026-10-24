.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose
BACKEND := cd backend &&
FRONTEND := cd frontend &&
POSTGRES_USER ?= postgres
POSTGRES_DB ?= gae265_03_group_project

.PHONY: help
help: ## 列出所有指令
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## 安裝 Python 與前端依賴
	uv sync
	$(FRONTEND) pnpm install

.PHONY: up
up: ## 啟動所有服務並監看程式碼變動（docker compose watch）
	$(COMPOSE) up --build --watch

.PHONY: down
down: ## 停止所有服務
	$(COMPOSE) down

.PHONY: logs
logs: ## 追蹤服務 log（make logs s=backend 只看單一服務）
	$(COMPOSE) logs -f $(s)

.PHONY: migrate
migrate: ## 套用 migration 到開發資料庫
	$(BACKEND) uv run alembic upgrade head

.PHONY: migration
migration: ## 產生 migration：make migration m="add trips"
	@test -n "$(m)" || (echo '用法：make migration m="描述"' && exit 1)
	$(BACKEND) uv run alembic revision --autogenerate -m "$(m)"

.PHONY: db-reset
db-reset: ## 重建開發資料庫並套用 migration
	$(COMPOSE) exec -T db psql -v ON_ERROR_STOP=1 -U $(POSTGRES_USER) -d postgres \
		-c 'DROP DATABASE IF EXISTS "$(POSTGRES_DB)" WITH (FORCE)' \
		-c 'CREATE DATABASE "$(POSTGRES_DB)"'
	$(COMPOSE) exec -T db psql -v ON_ERROR_STOP=1 -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		-c 'CREATE EXTENSION IF NOT EXISTS vector'
	$(MAKE) migrate

.PHONY: test
test: ## 執行後端測試（只連 gae265_03_group_project_test 資料庫）
	uv run pytest -vs $(args)
