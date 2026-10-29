---
status: accepted
---

# insurance_agent 移植的資料與介面決策（D2、D4～D7）

移植計畫（`docs/migration/insurance-agent/README.md`）的決策點，使用者於 2026-10-29 全部沿用建議。D1 的名詞定在 `GLOSSARY.md`，D3 在 [ADR-0005](0005-embedding-1024-and-retrieval.md)。

| # | 決定 | 理由 |
| --- | --- | --- |
| D2 | 險種資料表照 `BaseTable`（UUID 主鍵），另加唯一的 `code` 欄位放 insCode。`plan_insurance` 的 FK 指向 UUID | `AGENTS.md` 硬約束；insCode 是業務代碼，不當主鍵才能改 |
| D4 | 國泰方案照常報價，條款警示標「條款未收錄，請向保險公司確認」。條文庫只有富邦 16 個險種 | 國泰條款 PDF 已從原型移除；要收錄再另開階段，從原型 git 歷史取回 |
| D5 | 費率先讀 repo 內的 JSON | 原型認定 JSON 是逐格對照 PDF 的來源；後台需要編輯費率時再匯入資料庫 |
| D6 | MCP Server 掛在 backend 的 `/api/mcp`（streamable HTTP） | 正式環境 Caddy 既有的 `/api/*` 轉送就涵蓋，不用改 Caddyfile |
| D7 | 後台第一版唯讀，用 `ADMIN_TOKEN` 標頭保護 | 正式環境在公開 VM 上，不能像原型只綁 127.0.0.1；正式登入另開 ADR |

## 待同意

- D1（保險商品／方案／險種的關係）與 D2（資料表欄位與 FK）需要組長同意，**狀態：待組長同意**。組長不同意時，先改 `GLOSSARY.md` 與這份 ADR，再開始第 1、2 階段。
