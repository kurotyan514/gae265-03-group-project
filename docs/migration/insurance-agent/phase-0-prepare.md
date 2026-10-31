# 第 0 階段：準備

目標：之後每個階段開工時，決策、套件、資料和開發環境都已經就緒。這個階段不寫功能程式碼。

## 步驟

### 1. 確認原型已 commit

在原型執行 `git -C /mnt/c/project/insurance_agent status --short`。

完成條件：輸出是空的，並記下 `git -C /mnt/c/project/insurance_agent rev-parse --short HEAD`，寫進這個階段 PR 的說明，作為移植的來源版本。輸出不是空的就停下來，請使用者先 commit。

### 2. 決策定案

逐一和使用者確認 README 的 D1～D7。D1 用 `/domain-modeling` 進行，結果寫進 `GLOSSARY.md`。其餘每項寫成一份 ADR（`docs/adr/0005-...` 起，格式照現有 ADR），或在 PR 說明列出「沿用建議」。

完成條件：D1～D7 每一項都有定案紀錄；需要組長同意的（D1、D2）註明已同意或待同意。

### 3. ADR-0004：LLM 不產生數字

把原型 `CLAUDE.md` 的「鐵則」1～7 寫成 `docs/adr/0004-llm-never-produces-numbers.md`：價格與保額由程式算、流程由程式決定、LLM 輸出片段由程式合併、LLM 文字過數字白名單、條款不明確時保留方案並附條文、費率表不進向量庫、資料有疑慮不猜。每條附原型的理由與對應的程式位置（移植後的新路徑）。

再在 `AGENTS.md` 的硬約束加一行指向 ADR-0004。

完成條件：七條全部寫進 ADR，`AGENTS.md` 有指向它的一行。

### 4. 檢索實驗結論

把原型 `design/research/2026-10-28-rag-chunk-embedding-comparison.md` 的結論（bge-m3 最好、nomic-embed-text 不適合中文、一條條文一段）摘要進 ADR（可以併入 D3 的 ADR）。

完成條件：結論與出處（原型檔名）寫進 ADR。

### 5. 新增套件

使用者同意後，執行：

```bash
uv add --package app pymupdf pgvector langgraph-checkpoint-postgres "psycopg[binary,pool]" mcp
```

這些套件在 Python 3.14 都有現成 wheel（2026-10-29 確認：pymupdf 1.27.2.3、pgvector 0.5.1、langgraph-checkpoint-postgres 3.2.0、mcp 1.30.0）。

完成條件：`uv.lock` 更新，`make doctor` 全 PASS（backend 會因 `uv.lock` 變動自動重建）。

### 6. 資料搬進 repo

從原型複製到 `backend/data/`：

| 原型 | 新位置 |
| --- | --- |
| `data/rates/*.json` | `backend/data/rates/` |
| `config/regions.json`、`thresholds.json`、`plan_products.json`、`fubon_insurances.json`、`query_synonyms.json` | `backend/data/config/` |
| `docs/*.pdf`（16 份富邦險種條款） | `backend/data/clauses/` |
| `tests/eval/*.json`、`tests/eval/README.md` | `backend/data/eval/` |

`config/rag_experiments.json` 不搬（實驗不移植）。

完成條件：檔案逐一比對 checksum 與原型相同（`sha256sum`）；`backend/data/README.md` 說明每個資料夾的來源與「費率 JSON 逐格對照 PDF，不手改」的規則。

### 7. 開發用模型對齊原型

原型的評估結果是用 `gemma4:e4b`（對話）與 `bge-m3`（向量）跑的。請使用者：

1. 在 Windows 執行 `ollama list`，確認兩個 model 都在（沒有就 `ollama pull`）
2. 把 `.env` 改成 `OLLAMA_CHAT_MODEL=gemma4:e4b`、`OLLAMA_EMBEDDING_MODEL=bge-m3`，重跑 `make up`

完成條件：`make doctor` 的「LLM 供應商可連線（ollama）」PASS。

## 不做

- 不寫功能程式碼、不建資料表（第 1、2 階段才做）
