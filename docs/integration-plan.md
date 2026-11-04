# 整合計畫

規格書 v3.3 與資料庫（24 張表）都已就位，5、6、7 號、登入、功能一由不同的人開發。目前「骨架齊了、接縫還沒接」。這份文件列出我們能先做的事，目標是讓每個人能**獨立開發、合併時不互相踩到、壞掉時由 CI 先擋下來**。

- 狀態：計畫（尚未實作）；各項完成後在「進度」欄打勾並更新日期
- 基準：main `ef03794`、migration `f624f0fef944`（2026-11-04）
- 相關文件：[sync-after-pull.md](agents/sync-after-pull.md)（合併後怎麼同步）、[contract-changelog.md](agents/handoff/contract-changelog.md)（契約變更紀錄）、[handoff/README.md](agents/handoff/README.md)（5、6、7 號交接）

## 1. 現況盤點

| 面向 | 現況 |
| --- | --- |
| 後端路由 | 已有：保單、事件、待辦、文件、送件、對話、方案、保費、報價。**沒有**：功能一推薦與比較、提醒、結案、下載全部文件、Google 授權端點 |
| Agent | 三個都只有 `fake`；`backend/app/agents/` 只有 `registry.py`；**沒有啟動時 import 真實實作的掛鉤**；`AGENT_*_IMPL` 名稱設錯要到請求時才報錯 |
| Google | `get_google_access()` 固定回 `UnavailableGoogleAccess`；`TOKEN_ENCRYPTION_KEY` 在 config 與 `.env*.example` 都沒有，但 `google_grant` 表已建 |
| 登入 | 只有測試登入；正式環境受保護路由會 401（ADR-0008 部分取代，沒有新 ADR） |
| 前端 | 只有首頁、登入、帳號、`/plans` 與 `/dev/*`；規格 1-1~1-5、2-1~2-5、0-6 沒有正式頁；MSW mock 不含 policies、incidents |
| 排程 | 沒有（ADR-0003 決定第一版不放 worker）；提醒信（R9）沒有執行機制 |
| CI | 只跑 lint、test、build；**不跑** migration、seed、e2e；測試用 `create_all` 建表，**完全沒驗 alembic** |
| 缺的檢查 | migration 單一 head、model 與 migration 漂移、OpenAPI client 是否最新、seed 能否載入 |
| 文件 | 有 handoff、changelog、同步手冊；**沒有**端到端整合順序、ADR 編號重複（兩份 0016）、沒有 CODEOWNERS 與 PR 範本 |

## 2. 行動計畫

優先序：**P0** 低成本、所有人受益，先做；**P1** 契約與接縫、前端並行開發；**P2** 需要團隊先決定，或屬於後續功能。

### P0　整合守門與共同語言

| # | 項目 | 做法 | 進度 |
| --- | --- | --- | --- |
| 1 | CI 加四道閘門（(a)(b) 已完成，由 `backend/tests/test_migrations.py` 在 `make test` 內跑，2026-11-04；(c)(d) 待做） | `.github/workflows/ci.yml`：(a) `alembic heads` 只能有一個 head；(b) 空資料庫 `alembic upgrade head` 後 `alembic check`，並補一個用 alembic 建表的測試（現在只有 `create_all`）；(c) `make client` 後 `git diff --exit-code frontend/src/client`；(d) `make seed` 後驗證筆數（險種 39、條文 677、事故類型 9、範本 31…） | ☐ |
| 2 | 契約測試對每個已註冊實作跑一次 | CI 以 matrix 或迴圈對已註冊的實作跑 `CONTRACT_AGENT_<n>=<名稱> make test args="-k contracts"`；誰破壞契約，PR 就紅燈 | ☐ |
| 3 | 啟動時驗證 agent 註冊 | `backend/app/agents/__init__.py` 依 `AGENT_*_IMPL` import 對應套件並註冊；名稱不存在就啟動失敗（現在是請求時才報錯） | ☐ |
| 4 | 補齊環境範本 | `.env.example` 已有 `AGENT_5/6/7_IMPL`、`POLICY_MAX_UPLOAD_MB`；只有 `.env.prod.example` 要補（`POLICY_MAX_UPLOAD_MB` 僅非 production 使用，可不補）；`TOKEN_ENCRYPTION_KEY` 等 Google 授權決定後再補 | ☐ |
| 5 | 擴充 `make doctor` | 檢查 alembic 版本等於 head、seed 筆數、`AGENT_*_IMPL` 名稱已註冊（`scripts/doctor.sh`） | ☐ |
| 6 | 協作規則 | `CODEOWNERS`（`contracts/`、`models/`、`api/`、`domain/incident/` 歸平台）；`.github/pull_request_template.md`（勾選「契約變更」「migration」「已更新 changelog」）；修正 ADR 0016 編號重複 | ☐ |

**P0 建議拆成四個 PR（互不相依，可並行）**

| PR | 內容 | 理由 |
| --- | --- | --- |
| A | #1(a)(b)：單一 head、alembic upgrade + check、alembic 建表測試 | 最容易讓大家的 migration 互撞，先擋；CI 已有 pgvector service，不用改環境 |
| B | #1(c)(d)＋#2：client 新鮮度、seed 筆數、契約測試對每個實作跑 | 同樣只動 `ci.yml` 與 Makefile，但要等 A 的 job 結構定案後再加，避免衝突 |
| C | #3＋#4＋#5：啟動驗證 agent、`.env.prod.example`、`make doctor` | 都是 `backend/app/agents/`、`scripts/doctor.sh` 的小改動 |
| D | #6：CODEOWNERS、PR 範本、ADR 0016 改號 | 純文件；**改號會影響已引用 0016 的連結，改前先 grep 全 repo**，並要先問 ADR 作者保留哪個編號 |

注意：CODEOWNERS 要搭配 branch protection 的「需要 code owner 審查」才有擋的效果，那是 GitHub 設定、不在 repo 裡，需有權限的人去開。

### P1　契約與接縫

| # | 項目 | 做法 | 進度 |
| --- | --- | --- | --- |
| 7 | 契約缺口總表與 contract v2 提案 | 寫成 `docs/agents/handoff/contract-v2-proposal.md`，再各開 issue。原則：**只新增、保留舊欄位**（例如 `is_done`），加 `CONTRACT_VERSION`，changelog 與測試對版本。已知缺口見下方 | ☐ |
| 8 | 平台端缺的規格流程 | 依 `todo_template.condition` 產生待辦；理賠申請書（整個行程一項）；新狀況合併（原型 `buildTodos`／`mergeTodos`／`syncForm` 是參考）；送件狀態轉換（`self_submitted`、`sent` 寫 `closed_at`，不可清除，結案後擋勾選與上傳）；下載全部文件；更新 `summary_at`、`last_step` | ☐ |
| 9 | 端到端整合測試 | 以 `backend/tests/contracts/test_flow.py` 為基礎擴充：保單 → 事件 → 追問 → 待辦 → 上傳 → 送件 → 結案 → 結案後被擋；另加 `make smoke`（對跑著的服務打幾個關鍵端點） | ☐ |
| 10 | 規格畫面對照路由 | 0-1、0-2、1-1~1-5、2-1~2-5、0-6 對應路由與負責人；以 `/dev/incident` 當理賠流程的行為參考，先建立正式路由骨架 | ☐ |
| 11 | 擴充 MSW mock | 補 policies、incidents、todos、documents、submission 的 handlers，型別來自 `frontend/src/client`；`VITE_MOCK=true` 可跑完整流程，前端不必等後端 | ☐ |

**已知契約缺口（item 7）**

- 5：「不適用」待辦的標記方式；`ClauseUpdate` 沒有 `conclusion`、`amount_note`；必問欄位型別目前只在資料庫
- 6：`TodoView` 沒帶 `document_code`、`keywords`、`requires_upload`；辨識通過時取代舊檔的語意
- 7：`ClaimPackager.build` 仍只拿單一事件，規格要整張保單；Gmail 草稿與 `drafted`；一次送件拆成多封信、多個 id；`AttachmentRef` 缺檔案大小
- 平台：`GoogleAccess` 需要能提供 `drive_folder_id`（或文件存放方式定案後的替代）

### P2　需要團隊先決定的事

每項先由提案者寫成 ADR，再排進開發。

| 決定 | 建議預設 | 影響 |
| --- | --- | --- |
| 正式環境怎麼登入 | 新 ADR 取代 ADR-0008 | 不決定就無法部署 |
| 理賠文件存放（Drive 或伺服器） | 先用伺服器／物件儲存，Drive 之後再議 | 影響 6 的實作與 `google_grant.drive_folder_id` |
| 提醒信執行方式 | 惰性檢查加外部排程腳本（`make remind`，由 cron 呼叫），不引入 worker | 要補或修正 ADR-0003 |
| 功能一比較紀錄 | 由功能一的人設計，先對齊 schema 命名 | 規格 3.4 要存 |
| 險種「每個方案各一份」（ADR-0016） | 暫不做，先確認是否真的需要 | 會動 `insurance.code` 全域唯一的假設與給 5、6、7 的契約 |
| `policy_submission.policy_id` 是否唯一 | 建議唯一 | 結案不可恢復 |
| Google 授權流程與 `TOKEN_ENCRYPTION_KEY` | 登入負責人提案後補 ADR | 6、7 無法真實運作 |

### P2　功能缺口（backlog）

- 功能一推薦 API（`backend/app/domain/recommend/` 已有邏輯，沒有路由）
- 提醒信排程與寄送（R9）
- Google 授權端點與 token 加密保管
- 真實 agent 實作：各自開發，掛 `AGENT_*_IMPL`
- e2e 進 CI（用 compose 起服務跑 `make e2e`，先用 fake agent）

## 3. 整合順序（誰擋誰）

1. **平台**：CI 閘門、啟動驗證、協作規則（P0）→ 所有人受益
2. **團隊會議**：決定 P2 表中的登入、文件存放、提醒信
3. **平台**：contract v2 → 5、6、7 依新契約實作
4. **前端**：骨架與 mock 先行，後端流程完成後換成真實 API
5. 全部接上後：以 `make smoke` 加 e2e 做整合驗收

## 4. 驗證方式

- P0 每一道閘門都要故意製造一次失敗，確認會擋下：雙 head、model 漂移、client 過期、seed 筆數不符
- `make lint`、`make test`、`make e2e` 照常通過
- 每一項完成時更新本文件「進度」欄與 [contract-changelog.md](agents/handoff/contract-changelog.md)（有契約變更時）
