---
status: accepted
---

# 上傳保單只和條款庫比對方案；比對到才建立保單，問答一律用條款庫的條文

使用者上傳保單 PDF 的用途只有一個：確認他買的是條款庫裡有的商品方案。程式從保單文字抽出險種代碼（`T\d{3}`、`TA\d{2}`）或險種全名，與條款庫**完全比對**；某個方案（`app/domain/plans.py`）的險種**全部**比對到，才算比對到這個方案。比對不到就回 422，不建立任何資料。比對由程式做，LLM 不參與，也不做模糊比對。

比對到之後：

- 建立 `policy`（屬於使用者，記 `plan_id`）與 `policy_insurance`（方案所含的險種，上傳當下的快照）。
- 使用者選這份保單發問（`POST /policies/{id}/conversations`），建立 `conversation`（綁 `policy_id`），險種寫入 `conversation_insurance`。回答時才用 RAG 在這些險種的條文裡找資訊（[ADR-0005](0005-embedding-1024-and-retrieval.md)），數字規則仍照 [ADR-0004](0004-llm-never-produces-numbers.md)。
- 理賠待辦清單（[ADR-0011](0011-claim-flow-bounded-llm-judgement.md)）同樣綁在這個對話上建立的 `claim_case`。

取代 [ADR-0010](0010-policy-only-answers.md) 與 [ADR-0009](0009-policy-document-personal-data.md) 中保單段落的部分：**不再把保單內容存進資料庫**，所以沒有保單段落、保單向量，保單上傳也不做去識別化。原檔、原文、原檔名都不保存、不寫進 log。

## Considered Options

- **照 ADR-0010，保單段落與條款庫條文一起檢索**：能回答保單上寫的個人內容（被保險人、實際保額），但要存保單原文的去識別化版本與向量，個資風險與維護成本都高。
- **險種有任何一個比對到就收**：容易收進只買了方案一部分的保單，之後問答的範圍與使用者實際的契約不符。
- **方案的險種全部比對到才收**（採用）：寧可拒絕，也不用不完整的比對結果回答。

## Consequences

- 保單上寫的個人資料（保額、受益人、保險期間）查不到；問答只能回答條款庫的條文怎麼規定。需要時再另外決定，例如只抽出保險期間這類結構化欄位。
- 沒收錄的方案、或保單沒寫出險種代碼與全名的，會被拒絕。實際命中率要等真實保單樣本再看（目前以條款 PDF 當替身）。
- 方案目前是固定測試方案（`config/plans.json`），日後換成別組的資料來源，只要改 `app/domain/plans.py`。
- 去識別化模組（`app/policy/deidentify.py`）與 [ADR-0009](0009-policy-document-personal-data.md) 的規則保留，給理賠文件（流程圖的 6）與 `extra_notes` 使用，保單上傳不再呼叫它。
