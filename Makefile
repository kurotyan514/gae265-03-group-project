.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose
BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help
help: ## 列出所有指令
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## 安裝 Python、前端依賴與 pre-commit hook
	uv sync
	$(FRONTEND) pnpm install
	uv run pre-commit install

.PHONY: doctor
doctor: ## 檢查開發環境（工具版本、.env、服務、LLM 供應商），FAIL 附修復提示
	@scripts/doctor.sh

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

.PHONY: ingest
ingest: ## 解析 backend/data/clauses 的條款 PDF，匯入條文與向量到開發資料庫（會呼叫 embedding 供應商）
	$(BACKEND) uv run python -m app.ingest.catalog

.PHONY: db-reset
db-reset: ## 重建開發資料庫並套用 migration
	@# 帳號與資料庫名稱用 db 容器的環境變數，與 compose 讀到的 .env 一致
	$(COMPOSE) exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d postgres \
		-c "DROP DATABASE IF EXISTS \"$$POSTGRES_DB\" WITH (FORCE)" \
		-c "CREATE DATABASE \"$$POSTGRES_DB\"" \
		&& psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" \
		-c "CREATE EXTENSION IF NOT EXISTS vector"'
	$(MAKE) migrate

.PHONY: test
test: ## 執行後端測試（只連 gae265_03_group_project_test 資料庫）
	uv run pytest -vs $(args)

.PHONY: e2e
e2e: ## 執行 e2e 冒煙測試（先 make up；前端不在 localhost:5173 時設 E2E_BASE_URL）
	$(FRONTEND) pnpm exec playwright install chromium
	$(FRONTEND) pnpm exec playwright test $(args)

.PHONY: client
client: ## 從後端的 OpenAPI 產生前端 API client（frontend/src/client/）；改了 API 的 schema 要重跑
	uv run python -c 'import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))' > frontend/openapi.json
	$(FRONTEND) pnpm exec openapi-ts

.PHONY: lint
lint: ## ruff、Biome 的 lint 與格式檢查，加上型別檢查
	uv run ruff check .
	uv run ruff format --check .
	$(FRONTEND) pnpm exec biome check
	$(MAKE) typecheck

.PHONY: typecheck
typecheck: ## pyright 與 tsc 型別檢查
	uv run pyright
	$(FRONTEND) pnpm exec tsc --noEmit

.PHONY: format
format: ## ruff、Biome 自動修正與格式化
	uv run ruff check --fix .
	uv run ruff format .
	$(FRONTEND) pnpm exec biome check --write

DEPLOY_DIR ?= gae265-03-group-project

.PHONY: deploy
deploy: ## 部署到 VM：make deploy DEPLOY_HOST=user@<名稱>.<區域>.cloudapp.azure.com（DEPLOY_DIR 預設 ~/gae265-03-group-project）
	@test -n "$(DEPLOY_HOST)" || (echo '缺 DEPLOY_HOST，用法：make deploy DEPLOY_HOST=user@<名稱>.<區域>.cloudapp.azure.com' && exit 1)
	ssh $(DEPLOY_HOST) 'cd $(DEPLOY_DIR) && git fetch origin && git checkout main && git pull --ff-only origin main && docker compose -f compose.prod.yaml up -d --build'
