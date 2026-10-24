.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose
FRONTEND := cd frontend &&

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

.PHONY: client
client: ## 從後端的 OpenAPI 產生前端 API client（frontend/src/client/）；改了 API 的 schema 要重跑
	uv run python -c 'import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))' > frontend/openapi.json
	$(FRONTEND) pnpm exec openapi-ts
