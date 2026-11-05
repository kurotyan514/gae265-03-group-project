# 整合計畫

規格書 v3.3 與資料庫（24 張表）都已就位，5、6、7 號、登入、功能一由不同的人開發。目前「骨架齊了、接縫還沒接」。這份文件列出我們能先做的事，目標是讓每個人能**獨立開發、合併時不互相踩到、壞掉時由 CI 先擋下來**。

- 狀態：計畫（尚未實作）；各項完成後在「進度」欄打勾並更新日期
- 基準：main `ef03794`、migration `f624f0fef944`（2026-11-04）
- 相關文件：[sync-after-pull.md](agents/sync-after-pull.md)（合併後怎麼同步）、[contract-changelog.md](agents/handoff/contract-changelog.md)（契約變更紀錄）、[handoff/README.md](agents/handoff/README.md)（5、6、7 號交接）

## 0. 目前狀態（每次收工前更新）

更新日期：2026-11-05（深夜）

**做到哪了**
- 已合併：[#81](https://github.com/kurotyan514/gae265-03-group-project/pull/81)（5、6 號反饋與變更說明）、[#82](https://github.com/kurotyan514/gae265-03-group-project/pull/82)（migration 守門測試，整合守門 P0 的 #1 (a)(b) 完成）、[#83](https://github.com/kurotyan514/gae265-03-group-project/pull/83)（本文件）、[#86](https://github.com/kurotyan514/gae265-03-group-project/pull/86)（Google 登入與分段授權，Carol）、[#98](https://github.com/kurotyan514/gae265-03-group-project/pull/98)（契約 v2 提案）、[#99](https://github.com/kurotyan514/gae265-03-group-project/pull/99)（條文內容驗證模組，票 #89）、[#100](https://github.com/kurotyan514/gae265-03-group-project/pull/100)（待確認條文逐條放行、修改、刪除，票 #90）、[#101](https://github.com/kurotyan514/gae265-03-group-project/pull/101)（功能一首頁與比較紀錄，別人的）、[#102](https://github.com/kurotyan514/gae265-03-group-project/pull/102)（班機延誤文件清單與壞掉的 e2e）、[#103](https://github.com/kurotyan514/gae265-03-group-project/pull/103)、[#104](https://github.com/kurotyan514/gae265-03-group-project/pull/104)、[#107](https://github.com/kurotyan514/gae265-03-group-project/pull/107)（契約 v2 第 1 到 3 步）
- **契約 v2.0 的三步都已合併**：資料表（#103）、契約型別與 context 組裝與依結論建立待辦與 D10（#104）、上傳 API 接 `todo_id`、使用者確認「不確定」的文件、`PATCH` 放寬需上傳的待辦（#107）。後端 1434 個測試、完整 e2e 76 個通過。v2.1（7 號整張保單送件、Gmail 草稿、多封信）等 7 號輸入
- 別人開著的 PR：#84（6 號文件辨識，與 main 有衝突，要 6 號處理）、#87（規格書 v3.4）、#33（chunk 驗證工具草稿；檢查邏輯已搬進 #99，之後決定要不要關）
- 還沒開 PR 的工作：**預設的事故層級提醒**（`notices`：保險期間、通知期限；分支 `feat/default-notices`，已寫好待 commit）、**票 #91**（把內容驗證接進上傳 agent；已實作並驗證，暫存在 stash，待 commit）
- 條款上傳後自動內容驗證與逐條處理：規格 [#88](https://github.com/kurotyan514/gae265-03-group-project/issues/88)、票 #89 到 #97。#89、#90 已完成，#91 已實作；#92 到 #97 依序後面做。ADR 草稿還沒合併，編號要從 0023 起（0020 已是 Google 登入，0021、0022 在 #84），內容要改成「勘誤不存資料庫、管理者權限等 Google 登入接後台」
- 用真實條款檢查內容驗證：富邦 FUBON03 38 條通過 36、台安 TAIAN01 23 條通過 18，**安達 CHUBB05 與華南 HUANAN01 幾乎全部是待確認**（驗證用的版面規則 `verify_profiles.toml` 只有預設和富邦）。接上上傳流程後，這兩家的條款會整份變成待確認，需要補它們的驗證版面規則
- 理賠文件規則（`incident_catalog.json`）：班機延誤已完成（D01 新標題、不列 D11，#102）。其他類型的 D11 是否排除、D11 補身分證影本、D15 只在住院時要求、D17 對應「重新申辦證明」，以及定額型與實支實付型怎麼區分，由 Boris 與 6 號決定，還沒做

**下一步**
1. commit 並開 PR：預設提醒（`feat/default-notices`）、票 #91（驗證接進上傳 agent）；合併後從 main 同步
2. 補安達與華南的驗證版面規則（另開票；可派子 agent），否則 #91 上線後這兩家整份變待確認
3. #92（LLM 確認「工具不確定」的條文）到 #97，依序做
4. 契約 v2 的通知已先略過、後續有回覆再調整（5、6、7 號週五 11/6 下課前要交 prototype）
5. 把 ADR 草稿改成 0023 起並更新內容後提 PR

**後續待確認（先用預設值，不阻擋）**
- 5 號與 Boris：`coverage_keywords`（初始值）、`notices`（初始預設值：保險期間，班機與行李類「知悉事故後五日內通知」，其他類型不含天數的提醒）的正式版本
- 6 號：`incomplete`／`failed` 不存檔的強制規則；`stored_name`；ADR-0021 的資料夾名稱更正（6 號自己改）
- Leon：D02（機票與登機證）要不要兩份才算完成
- 7 號：v2.1 的 `build_for_policy` 要拿哪些資料、多封信的欄位、Gmail 草稿狀態

**等別人的事**
- 11/4 會議後仍要確認的事（見第 2 節「1104 規格書 v3.3 對齊會議」）：Jerry 的 SQL 工具與單一寫入者（建議工具只產生 `IncidentReply`，寫入由平台做）；S4 假授權（建議 CI 用假授權，Carol 授權完成後加選用的真實授權測試）；提醒信採 Celery＋Redis
- Azure PII 移除與 Demo 是否告知：Leon 與 6 號
- 「7 個方案只傳一份」：會議上沒人聽懂，待問提出者
- 理賠文件規則其餘項目與給付型態的區分：Boris 與 6 號
- 漏抓率抽樣（#97）量完之前，內容驗證不標「可信」

**已確認可跑的指令**（2026-11-05 深夜）
- `make lint` 通過；後端 1434 passed；完整 `make e2e` 76 passed

**已知風險**
- CI 只跑 lint／test／build，**不跑 e2e**（#81 與 #86 並行合併曾讓 e2e 在 main 上悄悄壞掉）；合併重要 PR 後，本機跑一次 `make e2e`
- `dev-incident`「已寄出」間歇性失敗：`dev.incident.tsx` 的 `submitAction` 先存送件結果、`open()` 又清掉（最近幾次完整 e2e 沒有出現，但原因沒修）
- 使用者自行勾選需上傳的待辦會讓 `all_todos_done` 為真但沒有文件（`without_document`），7 號的送件包要能處理沒有附件的待辦（v2.1）
- `all_todos_done` 包含整個行程共用的理賠申請書，同一張保單有多個事件時，D10 沒完成會讓每個事件都不能送件（Demo 只有單一事故，先接受）
- 內容驗證的誤報率與漏抓率尚未量過；險種在頁面中間才開始的合訂本，邊界檢查會誤判（#96 處理）
- 文件裡的 Python 程式碼區塊要先 `ruff format`，CI 的 lint 會檢查
- 多個人同時加 migration 會造成多個 head，#82 的守門測試會擋（#103 就遇到過，要把 `down_revision` 接到新的 head）

## 1. 現況盤點

| 面向 | 現況 |
| --- | --- |
| 後端路由 | 已有：保單、事件、待辦、文件、送件、對話、方案、保費、報價。**沒有**：功能一推薦與比較、提醒、結案、下載全部文件、Google 授權端點 |
| Agent | 三個都只有 `fake`；`backend/app/agents/` 只有 `registry.py`；**沒有啟動時 import 真實實作的掛鉤**；`AGENT_*_IMPL` 名稱設錯要到請求時才報錯 |
| Google | `get_google_access()` 固定回 `UnavailableGoogleAccess`；`TOKEN_ENCRYPTION_KEY` 在 config 與 `.env*.example` 都沒有，但 `google_grant` 表已建。**PR #86（Carol）已實作並合併**：`GrantGoogleAccess`、授權與撤銷路由、加密保管、第一次授權 Drive 時建資料夾，設定與範本一併補上 |
| 登入 | 只有測試登入；正式環境受保護路由會 401（ADR-0008 部分取代，沒有新 ADR）。**PR #86 已合併**：Google 登入，ADR-0020 取代 ADR-0008 |
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
| 4 | 補齊環境範本 | `.env.example` 已有 `AGENT_5/6/7_IMPL`、`POLICY_MAX_UPLOAD_MB`；只有 `.env.prod.example` 要補（`POLICY_MAX_UPLOAD_MB` 僅非 production 使用，可不補）；Google 相關設定（含 `TOKEN_ENCRYPTION_KEY`）由 PR #86 補進 `.env.example` 與 `.env.prod.example` | ☐ |
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

- 5：「不適用」待辦的標記方式（MVP 不需要，之後再做）；`ClauseUpdate` 沒有 `conclusion`、`amount_note`（資料表已有，規格 2-3a 的三種結論與額度說明要用）；必問欄位型別目前只在資料庫，問的過程中 `follow_up_questions` 是空的，v2 讓 `IncidentContext` 帶事故類型清單（代號、名稱、欄位型別、選項、問句），5 號 MVP 先唯讀 `incident_catalog.json`；重大注意事項（`todo_template.major_*`，最多 4 條）**由平台算好放進 `IncidentContext`**（11/5 決議），5 號不用整理也不用自己存
- 6：`TodoView` 沒帶 `document_code`、`keywords`、`requires_upload`；辨識通過時取代舊檔的語意
- 7：`ClaimPackager.build` 仍只拿單一事件，規格要整張保單；Gmail 草稿與 `drafted`；一次送件拆成多封信、多個 id；`AttachmentRef` 缺檔案大小
- 平台：`GoogleAccess` 需要能提供 `drive_folder_id`（或文件存放方式定案後的替代），並支援分段授權（沒有某項授權時回傳「需要授權」，不當成錯誤）
- 平台：PATCH 改成需上傳的待辦也能自行勾選並標「未附文件」（規格 v3.4，目前回 409）；理賠申請書（D10，整個行程一項）由平台在 5 號第一次回傳類型時建立，5 號不用 `TodoProposal` 補（避免重複）

**agent6 會議對齊事項的決議（2026-11-05，來源：1104 Lala_Agent 6 開會對齊事項）**

| 項 | 決議 | 歸屬 |
| --- | --- | --- |
| B1 一待辦可多份文件 | 做：拿掉 `incident_document.incident_todo_id` 唯一限制，何時完成由 6 號回傳的 `todo_complete` 決定 | contract v2＋migration |
| B3 `TodoView` 加 `document_code`、`requires_upload` | 做，可為空、相容舊程式；做完把契約測試裡「以 409 判斷要上傳」改掉 | contract v2 |
| B4／S4 契約流程測試 | 做：整套流程改假授權＋假存檔，另加「沒授權」劇本；6、7 號一起處理。11/4 會議說 S4「不需改，等 Carol 授權完成就能測」，但 CI 不可能有真實 Google 授權，建議假授權當預設，Carol 完成後再加一組選用的真實授權測試（待會議確認） | contract v2 |
| B5 使用者選待辦的 API | 做：使用者選待辦後，平台把文件對到待辦並標完成 | 平台 |
| B6 不存原檔名 | 做：`incident_document.file_name` 改存中性名稱（例：`D01_1.jpg`） | contract v2＋migration |
| B7 Drive 資料夾與取檔 | 由負責 Google 登入的 7 號開發者做；平台先定義介面契約：`GoogleAccess` 補上以 Drive 檔案編號取檔的能力，6 號把檔案編號存進資料庫，7 號用編號取檔，**不經過 6 號**（11/4 會議：直接從使用者 Drive 取檔、不經任何 agent；與 6 號表的 S2 合併） | 7 號＋平台定義契約 |

**1104 規格書 v3.3 對齊會議（2026-11-04）對本計畫的影響**

| 項 | 會議結論 | 對計畫的調整 |
| --- | --- | --- |
| 多檔上傳、檔名加 `_1`／`_2` | 與 B1、S3 相同 | 無衝突 |
| 手寫文件回「不確定」，使用者自行勾選，寄出後由保險公司判斷 | 與 B5 相同 | B5 的 API 要涵蓋這個語意 |
| 理賠文件規則 | **Boris 讀條文列各情境文件，6 號確認，兩人共用同一份 Excel**；Boris 的欄位與規範自己定 | 文件規則維護者是 Boris 與 6 號（先前寫成只有 6 號，已更正）；D11 也由兩人決定 |
| 5 號 MVP：「Agent → tool → function → SQL 建 DB 資料」 | Jerry 要先驗證，細節與後端組員（Boris）私下對 | **與 ADR-0015 衝突**：5 號只回傳結果，由平台驗證後寫入。建議工具函式只產生 `IncidentReply` 的內容，寫入仍由平台做（待與 Jerry 對齊） |
| 提醒信 | 傾向 Celery＋Redis，Carol 有餘力才做 | 見上方 P2 表 |
| 個資處理（Azure PII 移除、Demo 是否告知） | 組長評估後與 6 號討論，未決 | 6 號文件的去識別化規則先維持現狀，決議後更新 |
| 本週五（11/6）下課前各自交出可動的 prototype | — | PR #81 越早合併越好，開發者才能同步；6 號 prototype 先用假存檔 |
| 「7 個方案只傳一份」 | 會中沒人聽懂，待問提出者 | 先不處理 |

已做（2026-11-05，分支 `fix/agent5-feedback`）：B2 D02 改需上傳；5 號的類型代碼、班機延誤文件、問完才回類型。
D11（存摺封面與護照影本）是所有類型共用，條款庫查不到對應要求；已在注意事項註明「理賠款匯款用，條款未明訂這份文件」。是否保留或調整，以及理賠文件規則的維護，由 Boris 與 6 號（agent6）共同決定（11/4 會議結論 9）。

### P2　需要團隊先決定的事

每項先由提案者寫成 ADR，再排進開發。

| 決定 | 建議預設 | 影響 |
| --- | --- | --- |
| 正式環境怎麼登入 | **已完成（PR #86 已合併）**（ADR-0020：只用 Google 登入，授權分段）；部署前要補上正式環境的 Google 設定，缺任何一項後端就啟動失敗 | 不決定就無法部署 |
| 理賠文件存放 | **已決議（11/4 會議）**：原檔存使用者自己的 Google Drive，系統不保存；需補 ADR（修正 ADR-0009／初始 schema 的 `storage_path` 說法） | 影響 6、7 的實作與 `google_grant.drive_folder_id` |
| 提醒信執行方式 | 11/4 會議傾向 Celery＋Redis（Carol 有餘力才做；期限 24 小時或 3 天未定）。依團隊意見採用，但低優先，開工前先寫新 ADR 取代 ADR-0003，並在 compose 加回 Redis 與 worker（含 `compose.prod.yaml`） | 多兩個服務；原先建議的 `make remind` 加 cron 作為備案 |
| 功能一比較紀錄 | 由功能一的人設計，先對齊 schema 命名 | 規格 3.4 要存 |
| 險種「每個方案各一份」（ADR-0016） | 暫不做，先確認是否真的需要 | 會動 `insurance.code` 全域唯一的假設與給 5、6、7 的契約 |
| `policy_submission.policy_id` 是否唯一 | 建議唯一 | 結案不可恢復 |
| Google 授權流程與 `TOKEN_ENCRYPTION_KEY` | **分段授權**（11/5 登入負責人說明，修正 11/4 會議的「一起申請」）：登入時不要求權限，上傳理賠文件時才要 Drive（`drive.file`），寄信時才要 Gmail；**PR #86 已合併**（Carol，ADR-0020、`TOKEN_ENCRYPTION_KEY` 與資料夾建立都在裡面），6、7 可以接真實授權；6 號的 prototype 先用假存檔，不等授權。`GoogleAccess` 契約不用改授權部分，只需補 `drive_folder_id`（契約 v2） | 部署前要在正式環境補 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`PUBLIC_BASE_URL`、`TOKEN_ENCRYPTION_KEY`；金鑰遺失或更換後使用者要重新授權 |

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
