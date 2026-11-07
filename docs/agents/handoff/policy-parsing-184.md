# 保單解析與確認畫面（規格 #184）：交接說明

2026-11-07 寫。給接手的人，以及你們使用的 AI 助手。用字盡量白話；名詞以 [GLOSSARY.md](../../../GLOSSARY.md) 為準。

> 一句話：旅客上傳保單後，現在會看到一張確認卡，核對系統讀到的內容並修改讀錯的地方。**5、6、7 號的契約沒有改**，你們的程式不用動。五張都已完成。

## 1. 做到哪了

規格是 [#184](https://github.com/kurotyan514/gae265-03-group-project/issues/184)（已關閉）。拆成 5 張，全部已合併：

| 張 | 內容 | PR | 狀態 |
| --- | --- | --- | --- |
| 1 | 保單專用方案：富邦官網 C 方案（加購），不出現在方案清單、不能手選、不進推薦 | [#185](https://github.com/kurotyan514/gae265-03-group-project/pull/185) | 已合併 |
| 2 | 上傳保單的回應帶出完整解析結果（時分、目的地、商品名稱、附加條款、哪些欄位是讀到的），保單另存完整時間點 | [#193](https://github.com/kurotyan514/gae265-03-group-project/pull/193) | 已合併 |
| 3 | `PATCH /policies/{id}`：改保額、目的地、保險期間 | [#198](https://github.com/kurotyan514/gae265-03-group-project/pull/198) | 已合併 |
| 4 | 上傳後的確認卡（前端） | [#199](https://github.com/kurotyan514/gae265-03-group-project/pull/199) | 已合併 |
| 5 | 開事件時目的地預設帶保單的目的地 | [#203](https://github.com/kurotyan514/gae265-03-group-project/pull/203)（票 [#202](https://github.com/kurotyan514/gae265-03-group-project/issues/202)） | 已合併 |

另外 [#183](https://github.com/kurotyan514/gae265-03-group-project/pull/183)（手選保單可從過去比較帶入方案）是同一天做的，改的是同一頁的另一條路，已合併。

## 2. 旅客現在看到什麼

「出事了」頁（`/incident/new`）上傳保單成功後：

- 唯讀：保險公司、方案、保單上的商品名稱、含的險種與加購、適用附加條款。
- 可改：保額、目的地、保險期間（日期與時間，台灣時間）。
- 每個欄位標「✓ 由保單自動帶入，可修改」或「保單上讀不到，請自行填寫」，改了就拿掉。
- 按「確認，繼續」才存回（只送改過的欄位），回到「說明發生了什麼事」，保單已選好、目的地預填。

## 3. 資料與 API 變了什麼

| 項目 | 變更 |
| --- | --- |
| `policy` 資料表 | 新增 `start_at`、`end_at`（含時區，台北時間，只有上傳會填，手選為空）；migration `b7c41d2e9a10`。拉到要 `make migrate` |
| `POST /policies` 回應 | 新增公司、目的地、完整期間，以及只出現在這次回應、不存資料庫的 `product_name`、`riders`、`auto_filled` |
| `GET /policies`、`GET /policies/{id}` | 新增公司、目的地、`start_at`、`end_at`；時間一律以台北時間（`+08:00`）輸出 |
| `PATCH /policies/{id}` | 新端點。沒帶的欄位不動，`null` 是清空；方案與險種不能改（多帶欄位回 422）；只能改自己的保單 |
| `GET /plans` | 不列保單專用方案；手選建保單與選方案建立對話遇到它回 422 |
| `plans.json` | 方案可標 `upload_only` |

拉到之後要做：`make migrate`、`make client`（前端 client 會變）。`make seed` 不需要重跑。

## 4. 做了哪些決定（為什麼）

- **不用 LLM，不是 agent。** 保單解析是程式規則（流程圖的 4，負責的是平台）。名詞「保單解析」已加進 GLOSSARY，不要再叫「4 號 agent」或「保單辨識」（「辨識」指 6 號的文件辨識）。原因：保單上傳不做去識別化（[ADR-0013](../../adr/0013-policy-upload-matches-catalog-plans.md)），讓 LLM 讀 PDF 會和它衝突，數字也不能由 LLM 產生（[ADR-0004](../../adr/0004-llm-never-produces-numbers.md)）。
- **官網 C 方案是「保單專用方案」。** 它沒有保費與保障明細，不能編造，所以只能由保單比對到。決定與考慮過的做法見 [ADR-0026](../../adr/0026-upload-only-plans-for-official-site-products.md)。
- **上傳就建立保單，確認畫面用 PATCH 修改。** 沿用「比對不到就什麼都不建立」。代價見第 6 節。
- **完整時間另存，給 5 號的仍是日期。** 保單印到時分，但 5 號目前只比對日期，所以保留 `start_date`、`end_date` 不動，另存 `start_at`、`end_at`，之後要判斷到小時時不必請旅客重新上傳。
- **讀不到不拒絕。** 方案比對不到才拒絕（422）；保額、期間、目的地讀不到，保單照建，畫面標「請自行填寫」。

## 5. 各角色要知道的

- **5 號**：契約不變（仍是 2.2.0）。`IncidentContext.policy` 的 `start_date`、`end_date` 語意不變。完整時間點在資料庫裡，但**還沒進契約**；要判斷到小時時，請先找平台討論契約變更。
- **6 號**：保單上有「個人海外旅行不便保險班機延誤理賠文件簡化附加條款」，它會影響班機延誤要附哪些文件。這次只在確認卡顯示，**沒有**改任何文件判斷，也沒有存。要依它簡化文件清單，需要另開一張單。
- **7 號**：沒有影響。
- **功能一／方案資料的負責人**：`plans.json` 多了一個 `upload_only` 方案。它的正式內容（20 個保單代碼、名稱）是我依一份實際保單推出來的，**沒有人確認過**；投保連結留空。推薦只看有保費資料的方案，不受影響。
- **前端**：確認卡取代了 [#24](https://github.com/kurotyan514/gae265-03-group-project/issues/24)（保單上傳頁）要的「成功後顯示比對結果」。

## 6. 還沒做，以及已知的限制

**第 5 張已完成**（[#203](https://github.com/kurotyan514/gae265-03-group-project/pull/203)）：建立事件沒帶（或只有空白）目的地時，後端用保單的目的地，帶了以帶的為準；前端從「我的保單」改選既有保單時，目的地預設成那份保單的（保單沒有就保留已填的）。測試在 `backend/tests/contracts/test_default_destination.py` 與 `incident-policy-confirm.spec.ts`。

**已知的限制，沒有人在做**
- 上傳時保單就已建立：旅客在確認卡按「確認，繼續」之前離開，這份保單會留在「我的保單」，內容是系統讀到的值，沒有「未確認」的標記。目前也沒有刪除保單的 API（相關的 [#29](https://github.com/kurotyan514/gae265-03-group-project/issues/29) 是「刪除我的資料」，還沒做）。
- 只有富邦有保單代碼。其他公司（安達、泰安、臺產、華南）上傳仍會被拒。要擴充需要各家去識別化的保單樣本。
- 官網 C 方案「不含加購」時對應哪個方案，保單看不出來，這次沒處理。
- 解析只認得本專案已有的格式：期間在起日後面印了「零時」等沒認得的寫法時，日期照讀但沒有完整時間點；附加條款只接受以「條款」結尾的名稱。
- 確認卡沒有手動走查假資料模式（`VITE_MOCK=true`）；e2e 用真實後端。
- #199 合併後在 main（`5d0e9d8`）重跑完整 `make e2e`：116 passed、1 failed（`google-dev-incident.spec.ts:109`，單獨重跑全過，判定偶發）。
- #203 合併前再跑完整 `make e2e`：122 passed、2 skipped、0 failed。

## 7. 怎麼驗證

- 後端：`make test`（只連 `_test` 資料庫）。保單相關：`backend/tests/test_policies_api.py`、`test_policy_update_api.py`、`test_manual_policy_api.py`、`tests/policy/`。假富邦保單文字在 `backend/tests/policy/support.py`，不含個資。
- 前端：`make e2e`（要先 `make up`、`make seed`，後端要開 `DEV_LOGIN_ENABLED=true`）。相關的是 `frontend/e2e/incident-policy-confirm.spec.ts`，樣本 PDF 在 `frontend/e2e/fixtures/`（假的，由測試用的假文字產生）。
- 在分支的 worktree 裡驗證時：容器同步的是主目錄，所以要用分支自己的後端與前端（`uvicorn` 開 8001、`vite` 開 5174，`API_PROXY_TARGET` 指向 8001，再用 `E2E_BASE_URL` 跑）。

## 8. 接手時容易踩的坑

- **共用測試資料庫不能同時跑兩份 pytest。** `test_migrations` 會把整個結構砍掉重建，同時跑的另一份會整批失敗（一次出現 129 失敗、1498 錯誤）。要平行就一次只跑一份。
- **`frontend/src/client/` 是 `make client` 產生的，不手改。** 兩個 PR 在不同時間改了 API，`index.ts` 的匯出清單會因為在同一行而衝突（這次解了 3 次）。解法永遠是：取任一邊、重新 `make client`。若一直發生，可考慮讓匯出一個一行，或把「client 要最新」放進 CI。
- **migration 要接在唯一的 head 之後。** 別的 PR 先合併了新的 migration，就要把自己的 `down_revision` 改接過去（`test_single_migration_head` 會擋）。
- **主目錄常有別人在用。** 另開 `git worktree add ../xxx -b 分支 origin/main`，再 `ln -s` 主目錄的 `.env` 並 `make install`；不要在主目錄切分支或做 merge。
- **用字串替換改程式一定要斷言替換成功。** 這次有一個檢查因為格式化工具換了行而沒加進去，是測試抓到的。
- **自動 code review 要指定目錄**，否則它會看主目錄的別條分支。
- **開發資料庫要 `make migrate`** 才有 `start_at`、`end_at`；e2e 會在開發資料庫留下 `e2e-*@example.com` 的測試帳號。

## 9. 給 AI 助手的開場提示

> 你在接手保單解析與確認畫面（規格 #184）。請先讀 `docs/agents/handoff/policy-parsing-184.md`、`docs/adr/0026-upload-only-plans-for-official-site-products.md` 與 GLOSSARY 的「保單解析」「保單專用方案」。五張都已完成，要延伸（例如第 6 節的已知限制）時，先 `git fetch`，從最新 `origin/main` 另開 worktree，跑 `make doctor` 全部 PASS 再開始。完成後 commit 訊息要先給使用者確認。
