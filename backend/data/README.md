# backend/data

從原型 `insurance_agent`（來源版本 `512c7b1`）複製進來的資料。Dockerfile 只複製 `backend/`，資料放這裡才會進 image。檔案與原型的 sha256 完全相同。

| 資料夾 | 內容 | 原型來源 |
| --- | --- | --- |
| `rates/` | 費率表 JSON（富邦 6 份、國泰 2 份） | `data/rates/` |
| `config/` | 地區、門檻、費率表對條款、富邦險種清單、查詢同義詞 | `config/`（不含 `rag_experiments.json`） |
| `clauses/` | 富邦 16 個險種的條款 PDF，檔名即 insCode | `docs/` |
| `eval/` | 檢索與問答的驗收題與說明 | `tests/eval/` |

## 規則

- **費率 JSON 逐格對照保險公司 PDF，不手改。** 有疑慮的格子標為 `null` 並註明，不猜（見 [ADR-0004](../../docs/adr/0004-llm-never-produces-numbers.md)）。要改先回報使用者。
- 國泰沒有條款 PDF，只有費率表（見 [ADR-0006](../../docs/adr/0006-insurance-agent-migration-decisions.md) D4）。
- `config/plan_products.json` 的費率表對條款是原型的推測，需對照 PDF 核對。
