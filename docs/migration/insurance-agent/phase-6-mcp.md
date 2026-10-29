# 第 6 階段：MCP Server

目標：其他 AI（Claude Desktop、組員的 agent）透過 MCP 呼叫四個唯讀工具：`recommend`、`ask_plan_question`、`search_clauses`、`get_quote`。

依據：原型 `mcp_server/`、`design/mcp-connection.md`、`design/2026-10-28-next-features-spec.md` 第 ③ 節。

## 規則（照原型）

- 全部唯讀：不寫資料、不做選定、不上傳
- `recommend` 有狀態，沿用第 3 階段的對話圖與 session；回 `session_id`，呼叫端用同一個 `session_id` 回答追問；輸出 `status`（`needs_info`／`done`）、`questions` 或 `plans`
- 輸出一律結構化 JSON，每筆條文帶險種、條號、頁碼、原文
- 輸入上限：問句 300 字、`k` 最多 10、天數最多 365
- HTTP 用 `Authorization: Bearer <MCP_API_KEY>`，金鑰錯誤回 401；沒設 `MCP_API_KEY` 時 HTTP 端點不啟用
- 每來源限流 `MCP_RATE_LIMIT_PER_MIN`（預設 30）；原型的 `MCP_TRUST_PROXY` 在這裡固定為信任：正式環境一定在 Caddy 後面，來源 IP 取法與第 3 階段相同

## 步驟

### 1. 工具

移植 `mcp_server/tools.py` 到 `backend/app/mcp/`，工具內部呼叫第 1～4 階段的 domain 函式，不經過 HTTP。

完成條件：移植 `tests/test_mcp_server.py` 的工具案例（fake LLM），全部通過。

### 2. 傳輸

- **HTTP**：用 `mcp` SDK 的 streamable HTTP app 掛到 FastAPI 的 `/api/mcp`（D6）。SDK 的 session manager 要在 FastAPI 的 lifespan 裡啟動，否則請求會失敗。
- **stdio**：`docker compose exec -T backend python -m app.mcp --transport stdio`，給本機的 Claude Desktop。

設定 `MCP_API_KEY` 加進 `app.core.config`、`.env.example`、`.env.prod.example`。

完成條件：測試用 `mcp` SDK 的 client 連 `/api/mcp`：沒帶金鑰回 401、帶對的金鑰能列出四個工具並呼叫 `get_quote`。

### 3. 連線說明

把原型 `design/mcp-connection.md` 改寫成 `docs/mcp-connection.md`：用本 repo 的網址與指令，刪掉 ngrok 與 NAS 的部分（正式環境已有 HTTPS 網域）。

完成條件：照文件在 Claude Desktop 設定 stdio 連線，能呼叫 `search_clauses`（使用者手動確認）。
