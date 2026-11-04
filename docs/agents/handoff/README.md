# 5、6、7 號 agent 交接說明

給負責 **5（事件釐清）、6（文件辨識）、7（打包寄送）** 的成員，以及你們使用的 AI 助手。
先讀這份，再讀你負責的那一份：[agent-5-incident.md](agent-5-incident.md)、[agent-6-document.md](agent-6-document.md)、[agent-7-package.md](agent-7-package.md)。
決策背景在 [ADR-0015](../../adr/0015-agent-handoff-contracts.md)。名詞以根目錄 [GLOSSARY.md](../../../GLOSSARY.md) 為準。

## 一句話

平台（保單上傳、事件、資料庫、API）已經做好，你們只要實作一個 Python 類別：**輸入是唯讀的 `IncidentContext`，輸出是一個結果物件**。你們**不用碰資料庫、不用寫路由**，平台會檢查你們的結果符合契約後再寫入。

## 流程

```
使用者上傳保單 ──► 平台比對方案（4，已完成）
                       │ 出事了
                       ▼
        平台建立事件：預先放入「保單涵蓋的保障」與「基本待辦」
                       │
                       ▼
   ┌─► 5 事件釐清：和使用者對話 → 更新事件狀況、適用保障、新增待辦
   │                   │  使用者照待辦做事、上傳文件
   │                   ▼
   │   6 文件辨識：檢查文件、存到使用者的雲端 → 勾選對應待辦
   │                   │  所有待辦都完成
   │                   ▼
   └── 7 打包寄送：整理送件包 → 用使用者的 Gmail 寄給保險業務員
```

## 你們拿到什麼、要交出什麼

| | 你拿到（輸入） | 你交出（輸出） | 契約檔 |
| --- | --- | --- | --- |
| **5** | `IncidentContext`、使用者這句話、`AgentServices`（條款檢索） | `IncidentReply` | `backend/app/contracts/incident_agent.py` |
| **6** | `IncidentContext`、`UploadedFile`、`UserContext`、`GoogleAccess` | `Recognition` | `backend/app/contracts/document_agent.py` |
| **7** | `IncidentContext`（build）；再加收件人、使用者、`GoogleAccess`（send） | `ClaimPackage`、`SendResult` | `backend/app/contracts/package_agent.py` |

所有 agent 共用的唯讀資料模型在 `backend/app/contracts/common.py`（`IncidentContext`、`PolicySummary`、`TodoView`…）。
**這些契約檔就是規格**：欄位、型別、docstring 裡的規則都要看。想改契約請先跟平台負責人討論，不要自己改。

## 單一寫入者：誰能決定什麼

| 內容 | 決定者 | 平台會驗證 |
| --- | --- | --- |
| 建立事件、預設保障、基本待辦、對話、訊息儲存 | 平台 | — |
| 事件類型、標題、事件狀況、適用保障、新增待辦、助手訊息、出處 | **5** | 類型存在；保障在保單涵蓋內；出處是條款庫真的有且屬於保單險種；待辦範本屬於該類型；只能新增待辦、不能改 `is_done` |
| 文件辨識結果、存雲端、勾選對應待辦 | **6** | 待辦屬於這個事件；`recognized` 一定有 `storage_path`；`todo_complete` 只能出現在已辨識且有對應待辦的結果 |
| 送件包、寄送結果 | **7** | 所有待辦完成才能送件；附件只能是辨識通過的文件 |
| 使用者手動勾選待辦 | 平台 | `done_by` 記為 user |

違反任何一條，API 會回 **502** 且一筆都不寫，訊息會說是哪一條（不含使用者內容）。

## 資料表（只讀，供你理解 `IncidentContext` 的來源）

`policy`／`policy_addon`（保單、方案、加購）· `incident`（事件）· `incident_type`／`todo_template`（固定資料）· `incident_fact`（狀況）· `incident_clause`（適用保障：險種＋章）· `incident_todo`（事件待辦）· `incident_document`（上傳文件）· `incident_submission`（送件狀態）· `conversation`／`message`／`message_citation`（對話與出處）· `insurance`／`insurance_rule`（條款庫）。
欄位定義在 `backend/app/models/`，HTML 版的資料庫結構是設計依據。

## 本機怎麼跑

```bash
make doctor            # 全部 PASS 才繼續（FAIL 通常是 make up 沒開）
make test args="-k contracts"   # 契約測試，預設跑假實作
```

`backend/app/contracts/fakes.py` 有三個假實作（`FakeIncidentAgent` 等）：不呼叫 LLM、結果固定，
是你開發時的替身，也是「輸出長什麼樣子才算對」的範例。**先看它們再寫你的**。

API（`/api/v1`，Swagger 在 `/docs`）：

| 動作 | 端點 | 會呼叫 |
| --- | --- | --- |
| 建立事件 | `POST /policies/{policy_id}/incidents` | 5 的 `start` |
| 使用者說話 | `POST /incidents/{id}/messages` | 5 的 `reply` |
| 讀事件（就是 `IncidentContext`） | `GET /incidents/{id}` | — |
| 手動勾選 | `PATCH /incidents/{id}/todos/{todo_id}` | — |
| 上傳文件 | `POST /incidents/{id}/documents` | 6 的 `recognize` |
| 預覽送件包 | `GET /incidents/{id}/package` | 7 的 `build` |
| 送件 | `POST /incidents/{id}/submission` | 7 的 `send` |

## 接上你的實作（三步）

1. 在 `backend/app/agents/<你的名稱>/` 寫實作，符合契約裡的 `Protocol`。
2. 在 `backend/app/agents/registry.py` 註冊：`register_incident_agent("my_agent", MyAgent)`（6 用 `register_document_recognizer`，7 用 `register_claim_packager`）。工廠函式不接收引數。
3. 跑契約測試驗證：`CONTRACT_AGENT_5=my_agent make test args="-k contracts"`（6 用 `CONTRACT_AGENT_6`，7 用 `CONTRACT_AGENT_7`）。要在本機手動試，把 `.env` 的 `AGENT_5_IMPL=my_agent`（6、7 同理）再重啟 `make up`。

測試全過，你的實作就能跟其他兩位的假實作或真實作一起跑。你可以另外加自己的單元測試（放 `backend/tests/agents/<名稱>/`），
但**契約測試不要改**；如果你認為契約有問題，開 issue 討論。

## 所有 agent 都要遵守

1. **LLM 不產生數字**（[ADR-0004](../../adr/0004-llm-never-produces-numbers.md)）：金額、天數、保額只能從保單（`ctx.policy`）或條款原文（`AgentServices.search_rules`）原樣取用。LLM 寫的文字要用白名單檢查數字。
2. **流程由程式決定**（[ADR-0011](../../adr/0011-claim-flow-bounded-llm-judgement.md)）：要問什麼、問幾次、何時結束是程式決定；LLM 只負責聽懂與說人話，唯一例外是 5 最多 2 題有界追問。
3. **個資**（[ADR-0009](../../adr/0009-policy-document-personal-data.md)）：`description`、使用者訊息、文件內容可能含姓名、身分證字號、保單號碼等。送進 LLM 或寫進 log 之前用 `backend/app/policy/deidentify.py` 去識別化；log 與錯誤訊息**不放使用者內容**。
4. **出處要能驗證**：引用條文必須是 `search_rules` 實際檢索到的結果，平台會再核對；不要憑記憶寫條號。
5. **LLM 呼叫要可替換**：參考 `backend/app/ingest/agent.py`（`llm_classify`）：用一個可注入的 async 函式包住 LLM 呼叫，測試時用假的。測試不連網、不需要 API key（`LLM_PROVIDER=fake`）。
6. **不直接寫資料庫、不 import FastAPI**：agent 只回傳結果；只依賴 `app.contracts` 與你自己的程式。
7. **沒有 Google 授權不要丟例外**：`GoogleAccess.access_token(...)` 回傳 None 時，6 回 `needs_review`、7 回 `failed`，並在 `reason` 說明「請使用者先授權」。授權取得與保管由平台做，目前還沒有（需要 Google 審核 `drive.file`、`gmail.send` scope）。

## 登入與 Google 授權的變更

Google 登入已從平台移除（`refactor/remove-google-login`），**對你的實作沒有影響**：

- 契約不變：`backend/app/contracts/`、`IncidentContext`、`UserContext(user_id, email)`、`GoogleAccess` 都沒動，假實作與契約測試照舊。
- `GoogleAccess` 目前仍一律回 `None`（平台還沒有保管 Google 授權）。6 回 `needs_review`、7 回 `failed` 的規則不變，之後平台接上授權時你不用改程式。
- 本機呼叫事件 API 需要登入：`.env` 設 `DEV_LOGIN_ENABLED=true` 後用 `POST /api/v1/auth/dev-login`；寫測試用 `app.dependency_overrides[current_user]`。
- `.env` 裡的 `GOOGLE_*`、`ALLOWED_EMAILS`、`PUBLIC_BASE_URL` 已不使用，留著不影響。
- 正式環境的登入方式尚未決定，細節見 [google-login.md](google-login.md)（寫給之後接手登入的人，你不需要讀）。

## 開發環境注意

- 後端程式在 `backend/app/`，改了會自動重新載入；測試在本機跑（`make test`）。完整規則見 [dev-environment.md](../dev-environment.md)。
- 套件用 uv：`uv add --package app <套件>`；不要手改 `uv.lock`。
- 不要改 `backend/app/contracts/`、`backend/app/models/`、`backend/app/domain/incident/`、`backend/app/api/`（平台負責）；需要改請先討論。
- commit 前 `make lint` 與 `make test` 要過；commit 訊息用繁體中文加 Conventional Commits 前綴。

## 給 AI 助手的起手提示（整段貼給它）

> 你在協助我實作旅遊保險助手專案的一個 agent。請先依序閱讀：`docs/agents/handoff/README.md`、我負責的那份說明（agent-5／6／7）、`backend/app/contracts/` 全部檔案、`backend/app/contracts/fakes.py`、`docs/adr/0015-agent-handoff-contracts.md`、`docs/adr/0004-llm-never-produces-numbers.md`、`docs/adr/0009-policy-document-personal-data.md`。
> 規則：回答一律用繁體中文與台灣用語；只實作契約規定的 Protocol，不改 `app/contracts`、`app/models`、`app/api`；不直接寫資料庫；LLM 不產生數字；使用者內容先去識別化、不進 log；LLM 呼叫用可注入的函式，測試用假的、不連網。
> 工作方式：先用 `make doctor` 確認環境，先寫測試（參考 `backend/tests/contracts/`）再實作；完成後跑 `make lint` 與 `CONTRACT_AGENT_<5|6|7>=<註冊名稱> make test args="-k contracts"`，全過才算完成。遇到契約不清楚的地方先問我，不要自己猜。
