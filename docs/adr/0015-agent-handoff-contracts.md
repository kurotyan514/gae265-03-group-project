---
status: accepted
---

> **後續變更（2026-11-04）**：`incident_submission` 已改為以保單為單位的 `policy_submission`；`incident_todo` 的 `is_done` 改為 `status`。契約變更見 [contract-changelog.md](../agents/handoff/contract-changelog.md)。

# 5、6、7 號 agent 以共用資料庫、REST 與純 Pydantic 契約交接；agent 只回傳結果，由平台驗證後寫入

保單上傳（4）之後的流程分給不同成員開發：**5**（事件釐清、問答、待辦）、**6**（文件辨識）、**7**（打包追蹤與寄送）。為了讓大家能同時開發、各自測試，先定出交接契約與假實作。

## 流程

1. 使用者上傳保單，平台比對到方案（[ADR-0013](0013-policy-upload-matches-catalog-plans.md)）。
2. 出事時使用者選這張保單：**平台建立事件**，預先放入保單涵蓋的保障（`incident_clause`）與依待辦範本（`todo_template`）建立的基本待辦（`incident_todo`；事件類型還沒判斷出來時先用「其他」類型的範本），並建立事件問答對話。
3. 平台呼叫 **5**。使用者與 5 釐清狀況，5 回傳要更新的 `incident_fact`、事件類型、適用保障與新增的待辦；之後使用者每說一句話呼叫一次。
4. 使用者依待辦做事、上傳文件：平台呼叫 **6**。6 檢查文件、存到使用者的雲端、回傳辨識結果；通過就勾選對應待辦。
5. 所有待辦都完成後，平台才允許送件：平台呼叫 **7** 整理送件包，使用者確認收件人後，7 用使用者自己的 Gmail 寄給保險業務員。

## 決定

- **契約以 HTML schema 的名稱為準**：`incident`、`incident_fact`、`incident_clause`、`incident_todo`、`todo_template`、`incident_type`、`incident_document`，`conversation` 加 `kind`／`incident_id`。原本沒人使用的 `claim_case`、`checklist_item`、`claim_document`、`claim_submission` 已移除。
- **交接方式是共用資料庫加 REST，不用 MCP**：全部在同一個 FastAPI 服務（[ADR-0001](0001-single-vm-docker-compose-deploy.md)、[ADR-0003](0003-no-background-worker-yet.md)），沒有新服務要部署、使用者登入身分不用跨行程傳遞。契約（`app/contracts/`）是純 Pydantic 與 `Protocol`，不依賴 FastAPI，日後要包成 MCP tool 不用改。
- **agent 不碰資料庫**：每個 agent 是 `輸入 → 結果` 的函式，拿到唯讀的 `IncidentContext` 與少數服務（條款檢索），回傳結果；平台檢查結果符合契約後，在同一個交易裡寫入，違反就回 502 且一筆都不寫。這讓三位成員只要對著 `app/contracts/` 寫與測試，不需要理解彼此的資料表。
- **誰能決定什麼**：

| 內容 | 決定者 | 平台的驗證 |
| --- | --- | --- |
| 建立事件、預設保障與基本待辦、對話、訊息儲存 | 平台 | — |
| 事件類型、標題、`incident_fact`、適用保障、新增待辦、助手訊息與出處 | 5 | 類型存在；保障在保單涵蓋內；出處是條款庫真的有且屬於保單險種；待辦範本屬於該類型；只能新增、不能改 `is_done` |
| 文件辨識結果、存雲端、勾選對應待辦 | 6 | 待辦屬於這個事件；`recognized` 一定有 `storage_path`；`todo_complete` 只能出現在已辨識且有對應待辦的結果 |
| 送件包、寄送結果 | 7 | 所有待辦完成才能送件；附件只能是辨識通過的文件 |
| 使用者手動勾選待辦 | 平台 | `done_by` 記為 user |

- **`incident_clause` 先由平台放入，之後由 5 整組取代**：事件一開始適用的保障就是保單涵蓋的全部，5 釐清後再收斂並寫上理由。
- **Google 授權由平台保管**：6 存雲端需要 `drive.file`、7 寄信需要 `gmail.send` scope（目前登入只有 `openid email profile`，見 [ADR-0008](0008-google-oauth-cookie-session.md)），這需要 Google 審核。契約先定義 `GoogleAccess`（要 token，沒有就回 None），目前的實作一律沒有 token；agent 遇到沒有授權要回報「請使用者先授權」而不是丟例外。
- **假實作與契約測試**：`app/contracts/fakes.py` 是三個可重現的假 agent；`tests/contracts/` 用同一組測試驗證任何實作。成員實作完註冊到 `app/agents/registry.py`，設 `AGENT_5_IMPL`／`AGENT_6_IMPL`／`AGENT_7_IMPL`（測試用 `CONTRACT_AGENT_5`／`6`／`7`）即可切換。

## 與 HTML schema 的差異（需要設計者確認）

1. `incident_clause` 存 `insurance_id`（HTML 的保險商品）+ `section`（章），不指到單一條款：我們的條款庫是官網合訂本拆出來的險種，保障項目對應「險種 + 章」。
2. `incident_type` 多一個穩定的 `code`（給程式辨識，agent 回傳類型時用）；沒有 `concern_id`（在意項目表尚未實作）。
3. `incident` 的目的地存文字 `destination`（目的地表尚未實作）。
4. `incident_todo` 多一個 `done_by`（user／agent）：讓使用者看得出哪些是系統判斷完成的。
5. `incident_document` 多辨識欄位（`recognition_status`、`document_kind`、`recognition_reason`），回應 #36 的待釐清事項。
6. 新增 `incident_submission`（7 的送件狀態），HTML schema 沒有 7 的表。
7. `conversation` 的事件問答同時記 `policy_id`（HTML 只有 `incident_id`），方便檢索範圍沿用保單的險種。

## Consequences

- 原檔存放與 [ADR-0009](0009-policy-document-personal-data.md)「不保存原檔」衝突：6 要把文件存到使用者的雲端，伺服器只留 `storage_path`。這需要 6 的負責人與使用者確認後再實作。
- 事件類型與待辦範本的內容由維護後台資料的成員提供；`app/contracts/fakes.py` 的 `seed_sample_catalog` 只是測試與本機用的範例。
- `description` 與使用者訊息可能含個資：agent 送進 LLM 或寫進 log 之前必須去識別化（`app/policy/deidentify.py`）。
- 前端頁面不在這一輪；`GET /incidents/{id}` 回傳的就是契約的 `IncidentContext`，前端可以直接用。

（`message_citation` 與 HTML 的 `message_citations` 一致，沒有差異。這些差異已用紫色標在 HTML schema 上。）
