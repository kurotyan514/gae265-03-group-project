# 第 8 階段：正式環境

目標：移植後的系統跑在 ADR-0001 的 Azure VM 上，用 Azure OpenAI，目標使用者能實際試用；評估結果有 Azure 版本。

## 步驟

### 1. 設定

`.env.prod.example` 補上移植新增的設定：`EMBEDDING_DIMENSIONS=1024`、Azure 的 chat 與 embedding deployment（embedding 用 text-embedding-3-large 並指定 1024 維，見 D3）、`ACCESS_CODE`、`MCP_API_KEY`、`ADMIN_TOKEN`。每項附註解：用途、是否必填、怎麼產生（金鑰用 `openssl rand -hex 32`）。

完成條件：`ENVIRONMENT=production` 下缺必填項時 backend 啟動失敗並說明缺哪個（照 `check_llm_provider` 的做法）。

### 2. 部署與匯入

使用者照 README「部署到 Azure」部署後，在 VM 上匯入條文：

```bash
docker compose -f compose.prod.yaml exec -T backend python -m app.ingest.clauses
```

完成條件：VM 上的資料庫筆數 16／281／281。

### 3. Azure 上的評估

在 VM 上（或本機 `.env` 暫時切到 `azure_openai`）跑 `make eval-retrieval`、`make eval-qa` 的同一支程式，報告檔名標 `azure_openai`。

完成條件：`docs/reports/` 有 Azure 版的檢索與問答報告，與 Ollama 版並列比較；差異照實記錄。

### 4. 驗收

- 用瀏覽器開正式網址：完成一輪推薦、問一題、選一個方案、刪除我的資料
- 本機跑 `E2E_BASE_URL=https://<網址> make e2e`
- MCP：用 `MCP_API_KEY` 從本機連 `https://<網址>/api/mcp` 呼叫 `get_quote`

完成條件：三項都成功，結果寫進 PR 說明。
