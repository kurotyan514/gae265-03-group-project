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

.PHONY: eval-documents
eval-documents: ## 文件辨識驗收：讀 DOCUMENT_EVAL_DIR 的資料集（repo 外），照片會送 Azure（args="--model layout" 可切換）
	$(BACKEND) uv run python -m app.eval.documents $(args)

.PHONY: eval-retrieval
eval-retrieval: ## 跑檢索驗收題，報告寫到 docs/reports/（會呼叫 embedding 供應商）
	$(BACKEND) uv run python -m app.eval.retrieval

.PHONY: eval-incident
eval-incident: ## 5 號穩定度量測：真模型走完整對話，看有沒有產生正確的待辦（先 make up；會呼叫 LLM 供應商；args="--runs 2 --only 行李"）
	$(BACKEND) uv run python -m app.eval.incident_stability $(args)

.PHONY: eval-subchunk
eval-subchunk: ## 子塊檢索評估：用 data/eval/subchunk_questions.json 比較整條向量與子塊向量（只讀；args="--configs 800:300 --out docs/reports/x.md"；會呼叫 embedding 供應商）
	$(BACKEND) uv run python -m app.eval.subchunk $(args)

.PHONY: reembed
reembed: ## 重新計算條文向量（embedding_text 改了之後用；args="--insurance CHUBB06" 只算指定險種；會呼叫 embedding 供應商）
	$(BACKEND) uv run python -m app.ingest.reembed $(args)

.PHONY: export-seed
export-seed: ## 把開發資料庫的險種、條文與向量匯出成 backend/data/seed/catalog.json.gz
	$(BACKEND) uv run python -m app.seed export

.PHONY: plan-data
plan-data: ## 把 backend/data/source 的保費保障試算表轉成 backend/data/seed/plan_data.json（make seed 會匯入）
	$(BACKEND) uv run python -m app.ingest.plan_matrix

.PHONY: seed
seed: ## 讀 backend/data/seed/catalog.json.gz 與 plan_data.json 到資料庫（保留 UUID、不呼叫 embedding 供應商）；向量 model 名稱和本機不同時加 args="--as-model <名稱>"
	$(BACKEND) uv run python -m app.seed load $(args)

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
	# 測試登入端點要有開旗標才會註冊；client 要包含它，所以不依賴各人的 .env
	DEV_LOGIN_ENABLED=true uv run python -c 'import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))' > frontend/openapi.json
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
deploy: ## 部署到 VM：make deploy DEPLOY_HOST=user@<主機> REF=<tag 或 SHA>（該版 image 須已由 CD 打包；DEPLOY_DIR 預設 ~/gae265-03-group-project）
	@test -n "$(DEPLOY_HOST)" -a -n "$(REF)" || (echo '用法：make deploy DEPLOY_HOST=user@<名稱>.<區域>.cloudapp.azure.com REF=<tag 或 SHA>' && exit 1)
	ssh $(DEPLOY_HOST) 'set -e; cd $(DEPLOY_DIR) && git fetch --tags origin && git checkout --detach $(REF) && export IMAGE_TAG=$$(git rev-parse HEAD) && docker compose -f compose.prod.yaml pull && docker compose -f compose.prod.yaml up -d --wait --no-build'
