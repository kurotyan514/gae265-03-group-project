.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose
FRONTEND := cd frontend &&

.PHONY: help
help: ## 列出所有指令
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## 安裝 Python、前端依賴與 pre-commit hook
	uv sync
	$(FRONTEND) pnpm install
	uv run pre-commit install

.PHONY: up
up: ## 啟動所有服務並監看程式碼變動（docker compose watch）
	$(COMPOSE) up --build --watch

.PHONY: down
down: ## 停止所有服務
	$(COMPOSE) down

.PHONY: logs
logs: ## 追蹤服務 log（make logs s=backend 只看單一服務）
	$(COMPOSE) logs -f $(s)

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
