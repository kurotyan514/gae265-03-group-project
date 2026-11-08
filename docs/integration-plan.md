# 整合計畫

規格書 v3.3 與資料庫（24 張表）都已就位，5、6、7 號、登入、功能一由不同的人開發。目前「骨架齊了、接縫還沒接」。這份文件列出我們能先做的事，目標是讓每個人能**獨立開發、合併時不互相踩到、壞掉時由 CI 先擋下來**。

- 狀態：計畫（尚未實作）；各項完成後在「進度」欄打勾並更新日期
- 基準：main `ef03794`、migration `f624f0fef944`（2026-11-04）
- 相關文件：[sync-after-pull.md](agents/sync-after-pull.md)（合併後怎麼同步）、[contract-changelog.md](agents/handoff/contract-changelog.md)（契約變更紀錄）、[handoff/README.md](agents/handoff/README.md)（5、6、7 號交接）

## 0. 目前狀態（每次收工前更新）

更新日期：2026-11-07（收工）。下面「2026-11-07 收工狀態」是最新的；再往下的「做到哪了」「下一步」等是 11/6 的紀錄，已過時的項目以收工狀態為準

### 2026-11-07 收工狀態

**11/7 已合併**（main 在 `5d0e9d8`，之後加 #200、#203）
- 功能一：[#177](https://github.com/kurotyan514/gae265-03-group-project/pull/177)（在意事項 9 項、比較表合併列、1-4 五個固定情境與多列試算，關 #173～#176；含 data migration，拉到要 `make migrate`、`make client`）、#195（首頁最近的比較與全部比較頁）、#183（出事了手選保單可從過去比較帶入方案）
- 保單解析：#185（富邦官網 C 方案為保單專用方案）、#193（上傳保單回應帶出完整解析結果）、#198（`PATCH /policies/{id}`）、#199（上傳後出現確認卡，旅客可核對並修改）、#203（#202：建立事件沒帶目的地時用保單的目的地，改選保單時前端預填）；規格 #184 五張全部完成、已關閉，交接說明在 PR #200（`docs/agents/handoff/policy-parsing-184.md`）
- 5 號：#179（是非題接受自然語言肯定與否定，關 #158）、#186（延誤時數遇到否定、更正或多個時數照常追問，關 #180）
- 6 號：#144（文件合格規範，避免行李延誤誤勾待辦）、#191（理賠資料夾名稱更正為「好險有你 理賠文件」）、#192（6 號進度）
- 平台：#172（5 號回報日期時寫入事件的 `occurred_at`，關 #159）、#178（5 號回覆回來後重新讀取事件，修競態）、#171（修午夜偶發的測試）、#169、**#190**（確認「不確定」的文件後，Drive 與資料庫的檔名一起改成待辦名稱，**契約 v2.2.0**，關 #160）
- #190 的真 Google 驗證已由 6 號做完（見 #160 留言）：確認後改名、`drive.file` 能改 App 建立的檔案、改別人的檔案回 404 時確認照常完成、兩份確認到同一待辦是 `_1`、`_2`。序號規則 6 號審查通過

**契約**：`CONTRACT_VERSION = "2.4.0"`（11/8，新增 5 號回報待辦不適用，#232；2.3.0：`MessageView` 帶出 `quick_replies`、`citations`，選配，#212）。v2.2 只新增選配的 `DocumentRenamer`（沒實作的 6 號照樣能跑）；`DriveStorage` 協定多一個 `rename`，自己實作的人要補。變更紀錄在 [contract-changelog.md](agents/handoff/contract-changelog.md)

**5、6、7 號還開著的項目**
- 5 號（j3rryho）：[#181](https://github.com/kurotyan514/gae265-03-group-project/issues/181)（延誤超過 24 小時算錯，要問實際起飛日期）、[#133](https://github.com/kurotyan514/gae265-03-group-project/issues/133)、[#182](https://github.com/kurotyan514/gae265-03-group-project/issues/182)（問答帶入已釐清的事件狀況，`needs-info`）；[#73](https://github.com/kurotyan514/gae265-03-group-project/issues/73)（華南旅遊結束後十天內）
- 6 號（dinling1922）：後續兩張不擋合併的小項 [#196](https://github.com/kurotyan514/gae265-03-group-project/issues/196)（確認成 D10 時檔案要搬到行程資料夾）、[#197](https://github.com/kurotyan514/gae265-03-group-project/issues/197)（「待確認」序號跳號）
- 平台／Boris：[#194](https://github.com/kurotyan514/gae265-03-group-project/issues/194)（理賠文件規則依 Excel「事故理賠文件」修正：存摺、定額給付收據、證件遺失證明，指派 holysi）
- 7 號（carolwangwang）：[#154](https://github.com/kurotyan514/gae265-03-group-project/issues/154)（接上建立 Gmail 草稿，`mode="draft"` 目前仍回 `failed`）、[#165](https://github.com/kurotyan514/gae265-03-group-project/issues/165)（事故摘要的地點要讀事實 `place`）、[#155](https://github.com/kurotyan514/gae265-03-group-project/issues/155)（手動驗收寄信與草稿，要真 Google 登入）、[#74](https://github.com/kurotyan514/gae265-03-group-project/issues/74)

**驗證狀態**
- `make lint` 通過；後端 `make test` 1841 passed（11/7 合併 #183 前，Azure OpenAI 環境）
- 完整 `make e2e`：11/7 上午一次 106 passed、2 skipped、3 failed（`admin-bundles`、`compare-result`、`compare-scenarios`），單獨重跑那三個 spec 全過，判定偶發、原因沒查到。#177、#183 相關的 `compare`、`incident-flow`、`incident-import-from-comparison` 共 13 個通過。
- 合併 #199 後在 main（`5d0e9d8`）重跑完整 `make e2e`：116 passed、2 skipped、1 failed、4 did not run；失敗的是 `google-dev-incident.spec.ts:109`（卡在「還有待辦沒完成（409）」），單獨重跑整個 spec 6 個全過，判定偶發、原因沒查到。#199 新增的 `incident-policy-confirm` 通過
- #203 合併前再跑完整 `make e2e`：122 passed、2 skipped、0 failed（上面那個偶發失敗沒重現）；後端 `make test` 1916 passed
- 本機驗 e2e 時，容器是 `compose watch` 同步程式碼；切換分支後要等同步完成（曾因此誤判 7 個失敗），後端懷疑沒載入時先 `docker compose restart backend`，用 `localhost:8000/api/v1/openapi.json` 確認路由

**還沒驗到**
- 真的 Google 登入、Gmail 寄信與建立草稿（7 號，#154、#155）。6 號的 Drive 存檔、讀回與改名已用真 Google 驗過
- 範例事故類型只有班機延誤有真實條款依據

**下一步（建議順序）**
1. 偶發的 e2e 失敗（上午 3 個、合併 #199 後 1 個，不同 spec）若再重現，查原因（#203 合併前的完整 e2e 沒重現）
2. 7 號的 #154、#165，再和 #155 一起用真 Google 驗收寄信與草稿
3. 5 號的 #181；#194（理賠文件規則，Boris）
4. 還沒處理的人工項目：#114（11 條 FAIL 條文）、#97（漏抓率抽樣）、#106（保障項目到險種對照）
5. 理賠文件規則其餘類型（D11、D15、D17、定額型與實支實付型）：Boris 與 6 號決定

**本機環境**（holysi）：main 與遠端同步。`backup/dev-console`、`backup/phase-2` 是 10/29 的備份，留著；`~/worktree-patches-20261107/` 是三個舊 subagent worktree 的 patch 備份（沒推遠端，確認不需要後可刪）。遠端還有約 50 個舊分支沒清，其中有別人的（`feat/chunk-validator` 等），清之前要逐一確認

#### 以下是 11/6 的紀錄

**做到哪了**
- 已合併：[#81](https://github.com/kurotyan514/gae265-03-group-project/pull/81)（5、6 號反饋與變更說明）、[#82](https://github.com/kurotyan514/gae265-03-group-project/pull/82)（migration 守門測試，整合守門 P0 的 #1 (a)(b) 完成）、[#83](https://github.com/kurotyan514/gae265-03-group-project/pull/83)（本文件）、[#86](https://github.com/kurotyan514/gae265-03-group-project/pull/86)（Google 登入與分段授權，Carol）、[#98](https://github.com/kurotyan514/gae265-03-group-project/pull/98)（契約 v2 提案）、[#99](https://github.com/kurotyan514/gae265-03-group-project/pull/99)（條文內容驗證模組，票 #89）、[#100](https://github.com/kurotyan514/gae265-03-group-project/pull/100)（待確認條文逐條放行、修改、刪除，票 #90）、[#101](https://github.com/kurotyan514/gae265-03-group-project/pull/101)（功能一首頁與比較紀錄，別人的）、[#102](https://github.com/kurotyan514/gae265-03-group-project/pull/102)（班機延誤文件清單與壞掉的 e2e）、[#103](https://github.com/kurotyan514/gae265-03-group-project/pull/103)、[#104](https://github.com/kurotyan514/gae265-03-group-project/pull/104)、[#107](https://github.com/kurotyan514/gae265-03-group-project/pull/107)（契約 v2 第 1 到 3 步）、[#110](https://github.com/kurotyan514/gae265-03-group-project/pull/110)（預設的事故層級提醒）、[#111](https://github.com/kurotyan514/gae265-03-group-project/pull/111)（內容驗證接進上傳 agent，票 #91；支援多欄 PDF，並由險種代碼推斷公司以選版面規則）、[#112](https://github.com/kurotyan514/gae265-03-group-project/pull/112)（本節更新）、[#115](https://github.com/kurotyan514/gae265-03-group-project/pull/115)（`/dev/ingest` 的待確認條文處理，票 #94 的精簡版）、[#117](https://github.com/kurotyan514/gae265-03-group-project/pull/117)（條款上傳 e2e 修正）、[#118](https://github.com/kurotyan514/gae265-03-group-project/pull/118)（LLM 確認「工具不確定」的條文，票 #92）、[#119](https://github.com/kurotyan514/gae265-03-group-project/pull/119)（條文過長只提醒、不讓條文進待確認）、[#125](https://github.com/kurotyan514/gae265-03-group-project/pull/125)（入庫後檢索自檢、險種回報待處理條文數與自檢結果，票 #93）、[#126](https://github.com/kurotyan514/gae265-03-group-project/pull/126)（本節更新）、[#127](https://github.com/kurotyan514/gae265-03-group-project/pull/127)（驗證讀得到 `第N條【標題】` 的 CJK 相容字，票 #113）、[#129](https://github.com/kurotyan514/gae265-03-group-project/pull/129)（ADR-0023 條文入庫前逐條做內容驗證）、[#130](https://github.com/kurotyan514/gae265-03-group-project/pull/130)（後台條款上傳頁 `/admin/ingest`，上傳 API 改為需登入，票 #94）、[#134](https://github.com/kurotyan514/gae265-03-group-project/pull/134)（合訂本拆分清單存資料庫並偵測各險種起點，票 #95 第 1 步）、[#135](https://github.com/kurotyan514/gae265-03-group-project/pull/135)（拆分清單上傳 API 與 `/admin/bundles` 確認畫面，票 #95 第 2 步）、[#136](https://github.com/kurotyan514/gae265-03-group-project/pull/136)（已確認的清單逐險種入庫，驗證範圍限定到行層級，票 #96）
- **契約 v2.0 的三步都已合併**：資料表（#103）、契約型別與 context 組裝與依結論建立待辦與 D10（#104）、上傳 API 接 `todo_id`、使用者確認「不確定」的文件、`PATCH` 放寬需上傳的待辦（#107）。後端 1434 個測試、完整 e2e 76 個通過。v2.1（7 號整張保單送件、Gmail 草稿、多封信）等 7 號輸入
- **合訂本網頁上傳（票 #95、#96）已合併（11/6，#134 → #135 → #136）**；其他人拉取後要跑 `make migrate`（新增 `bundle_split` 表與 `pdf` 欄位）。流程：上傳 PDF（雜湊值相同沿用）→ 程式找每個「第一條」並往前找公司名稱開頭的標題行，產生候選邊界 → 管理者確認、改名、標不收、補漏、填各章保單代碼 → 依清單切開 → 每個收錄險種各建一個上傳工作，沿用單一險種的驗證與入庫流程。#136 用真實條款量（commit 訊息，未註明供應商）：通過 556 → 634 條（82% → 94%），確定錯誤 79 → 3 條
- 合併前用五份真實條款 PDF 走過一次（11/6，Azure OpenAI；加一個換行讓雜湊值不同，內容不變）：偵測的起點和已確認清單相符（華南 20／20、富邦 7／7、泰安 4／4、臺灣產物 17／17），安達漏了沒有「第一條」的「海外急難援助服務內容」（設計上偵測不到，本來就是不收）。華南走完上傳、儲存、試切、確認、入庫：8 個險種 120 條，與資料庫現有內容逐一相同；只有 HUANAN08 第 2 條停在待確認，原因是文字層把標題印兩次、標準答案是空的，屬誤報，修正在 [#141](https://github.com/kurotyan514/gae265-03-group-project/pull/141)（尚未合併，合併後要重新入庫確認）
- 別人開著的 PR：#131（1-4 情境試算與問答）、#132（5 號 agent v1，#128）、#84（6 號文件辨識，與 main 有衝突，要 6 號處理）、#87（規格書 v3.4）、#33（chunk 驗證工具草稿；檢查邏輯已搬進 #99，已留言請開發者關閉）
- 條款上傳後自動內容驗證與逐條處理：規格 [#88](https://github.com/kurotyan514/gae265-03-group-project/issues/88)、票 #89 到 #97。#89 到 #93、#113 已完成；#94 的後台頁面 #130 已合併（issue 還開著，剩下哪些項目未核對）；#95、#96 已合併；#97 人工作業。ADR 已合併為 ADR-0023
- 用真實條款檢查內容驗證（#111 之後）：通過率從 57% 提高到 81%，安達（3 欄）與華南（2 欄）已補驗證版面規則。當時仍有 131 條沒通過：險種從頁面中間開始 100 條（70 FAIL、30 WARNING，#96 處理）、工具不確定 18 條、需人工看 11 條 FAIL（#114）、`第N條【…】` 標題讀不到 2 條（#113）。之後 #118 讓 LLM 能放行約 30 條工具讀法不同的條文，#119 讓過長提醒（L1）不再擋入庫（約 6 條）；頁碼不同（T4）約 10 條量少，人工處理，不改規則
- 檢索自檢（#125 合併時，用真實條款、Azure `text-embedding-3-large`、前 3 名）：675/700 條找得到自己（96.4%）；38 個險種中 7 個低於預設門檻 0.95（CHUBB05、CHUBB06、FUBON03、FUBON04、FUBON05、HUANAN01、TFMI01，都是 40 條以上的大險種，各失敗 3 到 5 條）。預設的前 3 名與 0.95 是否合適，要看失敗條文後由 Boris 與 6 號決定
- 理賠文件規則（`incident_catalog.json`）：班機延誤已完成（D01 新標題、不列 D11，#102）。其他類型的 D11 是否排除、D11 補身分證影本、D15 只在住院時要求、D17 對應「重新申辦證明」，以及定額型與實支實付型怎麼區分，由 Boris 與 6 號決定，還沒做

**下一步**
1. 合併 #141（驗證修正）後，用 `/admin/bundles` 重新入庫華南，確認 HUANAN08 第 2 條不再停在待確認；#134 到 #136 合併後本機的 `make e2e` 還沒跑
2. #114（11 條需人工確認的 FAIL）：Boris 在 `/dev/ingest` 的待確認條文區處理，找共同原因
3. 保單代碼收尾（ADR-0016 的讀取端）：[#137](https://github.com/kurotyan514/gae265-03-group-project/issues/137)（`make seed` 不再覆蓋後台填的代碼）、[#138](https://github.com/kurotyan514/gae265-03-group-project/issues/138)（保單上傳比對改讀資料庫）已於 PR #146 完成；[#139](https://github.com/kurotyan514/gae265-03-group-project/issues/139)（移除退回讀檔、`config/policy_codes.json` 只留作 seed 初始資料、更新 ADR）已完成。不需要 migration，不影響 5、6、7 號契約
4. #94 剩餘項目（LLM 理由與檢索品質標示等）：對照 issue 內容核對 #130 做了哪些
5. #97（漏抓率抽樣，人工作業，量完才標「可信」）
6. 契約 v2 的通知已先略過、後續有回覆再調整（5、6、7 號週五 11/6 下課前要交 prototype）

**後續待確認（先用預設值，不阻擋）**
- 5 號與 Boris：`coverage_keywords`（初始值）、`notices`（初始預設值：保險期間，班機與行李類「知悉事故後五日內通知」，其他類型不含天數的提醒）的正式版本
- ~~6 號：`incomplete`／`failed` 不存檔的強制規則；`stored_name`；ADR-0021 的資料夾名稱更正~~ 已完成（11/7）：不存檔由平台強制檢查（違反回 502）；6 號回傳 `stored_name`；ADR-0021 與 GLOSSARY 的資料夾名稱已更正為「好險有你 理賠文件」（PR #191）
- Leon：D02（機票與登機證）要不要兩份才算完成
- 7 號：v2.1 的 `build_for_policy` 要拿哪些資料、多封信的欄位、Gmail 草稿狀態

**等別人的事**
- 11/4 會議後仍要確認的事（見第 2 節「1104 規格書 v3.3 對齊會議」）：Jerry 的 SQL 工具與單一寫入者（建議工具只產生 `IncidentReply`，寫入由平台做）；S4 假授權（建議 CI 用假授權，Carol 授權完成後加選用的真實授權測試）；提醒信採 Celery＋Redis
- Azure PII 移除與 Demo 是否告知：Leon 與 6 號
- 「7 個方案只傳一份」：會議上沒人聽懂，待問提出者
- 理賠文件規則其餘項目與給付型態的區分：Boris 與 6 號
- 漏抓率抽樣（#97）量完之前，內容驗證不標「可信」

**已確認可跑的指令**（2026-11-05 深夜；11/6 的 #134 到 #136 合併後尚未重跑 `make e2e`；#141 分支的 `make test` 為 1511 passed，不含 #134 到 #136）
- `make lint` 通過；後端 1434 passed；完整 `make e2e` 76 passed

**已知風險**
- 合訂本重新入庫時，條文的 `source_file` 會改成這次上傳的檔名（驗證時發現：用副本檔名上傳，119 條華南條文的來源檔名被改掉，已手動還原）；管理者上傳檔名不同的同一份 PDF，引用顯示的檔名就會跟著變，要不要保留原檔名還沒決定
- 上傳合訂本時不填公司，草稿存的 `company` 是空的（推斷的結果只用在偵測），確認時才被擋；API 說明寫「不填就從 PDF 推斷」，兩者不一致
- **保單代碼以資料庫為準**（已解決，#137～#139）：保單上傳比對只讀 `insurance.policy_codes`，`make seed` 只補上 `config/policy_codes.json` 有的代碼、不覆蓋後台填的。剩下的限制：抽代碼的規則只認 `T`＋3 位數與 `TA`＋2 位數（`policy/table.py`），保額靠固定代碼 `T068` 找；後台填其他格式的代碼目前抽不出來
- CI 只跑 lint／test／build，**不跑 e2e**（#81 與 #86 並行合併曾讓 e2e 在 main 上悄悄壞掉）；合併重要 PR 後，本機跑一次 `make e2e`
- `dev-incident`「已寄出」間歇性失敗：`dev.incident.tsx` 的 `submitAction` 先存送件結果、`open()` 又清掉（最近幾次完整 e2e 沒有出現，但原因沒修）
- 使用者自行勾選需上傳的待辦會讓 `all_todos_done` 為真但沒有文件（`without_document`），7 號的送件包要能處理沒有附件的待辦（v2.1）
- `all_todos_done` 包含整個行程共用的理賠申請書，同一張保單有多個事件時，D10 沒完成會讓每個事件都不能送件（Demo 只有單一事故，先接受）
- 內容驗證的誤報率與漏抓率尚未量過（#97）；險種在頁面中間才開始的合訂本，邊界檢查會誤判（#96 處理）
- 文件裡的 Python 程式碼區塊要先 `ruff format`，CI 的 lint 會檢查
- 多個人同時加 migration 會造成多個 head，#82 的守門測試會擋（#103 就遇到過，要把 `down_revision` 接到新的 head）

### 整合走查：5、6、7 號接進使用者正式流程（2026-11-06，#150／#156）

目的：把 5、6、7 號從各自的 `/dev/*` 開發頁，接進使用者的正式流程（`/incident/*`），用正式流程完整走一次。範例事件類型只有班機延誤有真實條款依據，所以只走班機延誤。

**環境設定**（切換 agent 不用改程式，只設環境變數；預設仍是 `fake`，CI 與契約測試依賴它）

| 設定 | 值 | 用途 |
| --- | --- | --- |
| `AGENT_5_IMPL` | `v1` | 5 號 v1（班機延誤）；需要 Azure OpenAI（`AZURE_OPENAI_*`）；`TYPESAFE_API_KEY` 留空＝不守門 |
| `AGENT_6_IMPL` | `document` | 6 號文件辨識；照片要 Azure Document Intelligence（`AZURE_DOCUMENT_INTELLIGENCE_*`），沒設時照片一律進「需要你確認」，有文字層的 PDF 不受影響 |
| `AGENT_7_IMPL` | `gmail`（真的寄信）或 `gmail-offline`（不連 Google，正式環境會報錯） | 7 號；`gmail-offline` 沒有 Google 授權，寄出與建草稿會回 `failed` 並說明要授權 |
| `DOCUMENT_DEV_FAKE_STORAGE` | `true` | 沒有 Google 授權時改用假的雲端存檔，文件不會真的存到任何地方（開發與展示用，正式環境不可開） |

拉到 [#161](https://github.com/kurotyan514/gae265-03-group-project/pull/161) 之後要跑一次 `make seed`，才會清掉舊資料庫裡一般事故類型（`other`）的舊待辦範本（11/2 範例資料的「取得事故證明」「填寫理賠申請書」）；不清的話每個新事件都會多出這兩筆，且和 D10 理賠申請書重複，6 號辨識理賠申請書就會「對到好幾項待辦」。

**走查步驟**（每一步都用正式流程的 API 或畫面，不用 `/dev/*`）
1. 登入（測試登入或 Google 登入）→ 首頁「出事了：幫我處理理賠」
2. 手選方案與保額建立保單（`POST /policies/manual`；選方案用 `GET /plans`、`GET /plans/{id}/sum-insured-options`）
3. 建立事件（`POST /policies/{id}/incidents`）說明狀況，回答 5 號的追問（日期、原定與實際起飛時間、延誤原因、是否搭第一班替代班機）。建立當下待辦是空的，問完且結論是「可能適用」才出現 3 項
4. 上傳文件（`POST /incidents/{id}/documents`）：`backend/app/agents/document/samples/` 的 `delay.pdf`（D01）、`boarding_pass.pdf`（D02）、`claim_form.pdf`（D10），另可加一份不相關的檔案看「需要你確認」
5. 勾完剩下的待辦（`PATCH /incidents/{id}/todos/{todo_id}`）
6. 預覽送件信（`GET /incidents/{id}/package`），再選送件方式（`POST /incidents/{id}/submission`，`mode` 為 `send`／`draft`／`self`，`fills` 放使用者填的空格）
7. 結案後確認不能再修改（傳訊息、上傳、再送件都回 409）

**結果**（真 5 號 v1＋真 6 號＋假 7 號，再用真 7 號離線版走一輪）

| 段落 | 結果 |
| --- | --- |
| 5 號 | 一句話抽出類型與地點，一次問一題；答「是」得到「可能適用」並產生待辦；答「否」得到「資訊不足」 |
| 6 號 | D01、D02、D10 辨識通過並自動勾待辦（D02 提示「還缺機票」）；不相關的檔案進「需要你確認」；選待辦確認後勾成使用者完成。11/7 PR #144 合併後再走一次：行李延誤證明與無關收據不勾待辦、進「需要你確認」；機票與登機證印在同一張就完成 D02；5 號結論不是「可能適用」時沒有事件待辦，延誤證明也不勾 |
| 7 號（離線版） | 送件信有「（請填寫＋項目）」空格；空格沒填完 `send` 回 409 並列出項目；收件者格式錯回 422；填完後離線版因沒授權回 `failed`；`draft` 目前回 `failed`（#154 還沒接）；`self` 結案 |
| 結案 | 傳訊息、上傳、再送件都回 409「事件已結案，不能修改」 |
| 畫面 | 四個正式畫面讀得到真資料，瀏覽器沒有 console 錯誤；e2e（真後端、假 agent）與假資料模式走過新的送件流程 |

**走查發現的問題與處理狀態**

| 問題 | 歸屬 | 狀態 |
| --- | --- | --- |
| 待辦重複（兩筆「填寫理賠申請書」），6 號對到好幾項待辦 | 平台 | 已修：[#157](https://github.com/kurotyan514/gae265-03-group-project/issues/157)（PR #161，需 `make seed`） |
| 結案後仍可傳訊息、上傳，再送件一次也成功（會寄出重複的信） | 平台 | 已修：[#152](https://github.com/kurotyan514/gae265-03-group-project/issues/152)（PR #162） |
| 使用者填的空格到不了 7 號，正式網站寄不出信 | 平台 | 已修：[#151](https://github.com/kurotyan514/gae265-03-group-project/issues/151)（契約 v2.1.0，PR #163）、[#153](https://github.com/kurotyan514/gae265-03-group-project/issues/153)（正式送件頁，PR #164） |
| 替代班機那題，自然語言的否定（「不是，我等的就是原本那班」）沒被接受，5 號重複問同一題 | 5 號 | 開著：[#158](https://github.com/kurotyan514/gae265-03-group-project/issues/158) |
| 5 號已記下發生日期，事件的 `occurred_at` 仍是空的（6 號用它命名 Drive 的事故資料夾，所以資料夾名稱沒有日期） | 平台 | 已修：[#159](https://github.com/kurotyan514/gae265-03-group-project/issues/159)（5 號回報 `date` 事實時寫入） |
| 需要手動確認的文件，確認後檔名仍是「待確認_1.pdf」（辨識通過的檔名正常） | 平台／6 號 | 開著：[#160](https://github.com/kurotyan514/gae265-03-group-project/issues/160)；修正在 PR #190（契約 v2.2.0），11/7 已用真的 Google Drive 驗證，等合併 |
| 7 號事故摘要的地點寫成「（請填寫地點）」，但 5 號已記下地點（7 號讀 `destination`，沒讀事實 `place`） | 7 號 | 開著：[#165](https://github.com/kurotyan514/gae265-03-group-project/issues/165) |
| 已有文件的待辦被使用者勾選時仍標「未附文件」，送件信同時寫「未隨信附上」與列在附件清單 | 平台 | 開著：[#166](https://github.com/kurotyan514/gae265-03-group-project/issues/166) |

**還沒驗到的部分**
- **真的 Google 登入、Drive 與 Gmail**：走查用測試登入，沒有走授權導向與導回；送件頁授權導回後還原已填內容、寄出與建立草稿的實際內容，都要有 Google 設定的人實際走一次（[#155](https://github.com/kurotyan514/gae265-03-group-project/issues/155)）。6 號的 Drive 存檔已在 11/7 用真的 Google 授權驗過：正式流程存進使用者的 Drive；確認後改名、改名被拒絕時沿用舊檔名，並用 Drive API 讀回檔名比對（見 #160 留言）
- **建立草稿**：7 號還沒接上（[#154](https://github.com/kurotyan514/gae265-03-group-project/issues/154)），目前一律回 `failed`
- **照片辨識**：11/7 在設有 Azure Document Intelligence 的環境走過正式流程：理賠申請書與登機證照片辨識通過，模糊照片回不通過。用評估資料集重跑一次（[#68](https://github.com/kurotyan514/gae265-03-group-project/issues/68)）還沒做
- **其他事故類型**：範例 catalog 只有班機延誤有真實條款依據
- 結案後重新整理，送件頁只知道「已結案」，不知道是寄出、草稿還是自己處理（後端沒有回傳送件結果）

**怎麼重跑**：設好上面的環境變數、`make seed`、重啟後端，照走查步驟走一遍；問題清單的格式是「步驟／現象／歸屬」，歸屬平台的當場修，歸屬 agent 的開票給負責人。走查的環境、結果與問題都記在 [#150](https://github.com/kurotyan514/gae265-03-group-project/issues/150)。

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
| 10 | 規格畫面對照路由 | 0-1、0-2、1-1~1-5、2-1~2-5、0-6 對應路由與負責人；以 `/dev/incident` 當理賠流程的行為參考，先建立正式路由骨架 | 部分：理賠流程的 `/incident/*` 四個路由已建（規格畫面編號對照還沒寫） |
| 11 | 擴充 MSW mock | 補 policies、incidents、todos、documents、submission 的 handlers，型別來自 `frontend/src/client`；`VITE_MOCK=true` 可跑完整流程，前端不必等後端 | ☑ `src/mocks/incident.ts`，說明在 `handoff/frontend-claim-flow.md` |

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
