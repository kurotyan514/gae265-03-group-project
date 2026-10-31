# 第 5 階段：選定方案記錄

目標：使用者在推薦卡片按「選這個」，系統記下當時的報價快照；使用者可以查看自己的選擇、一鍵刪除所有資料；不需要登入。

依據：原型 `web/selections.py`、`design/2026-10-28-next-features-spec.md` 的「身分（owner_id）」與第 ① 節。

## 規則（照原型）

- 瀏覽器產生 32～64 位十六進位的隨機 token 存 localStorage，用 `X-Owner-Token` 標頭送出；資料庫只存 token 的雜湊 `owner_id`
- 快照由伺服器從該 session 的檢查點（推薦結果）複製，不接受前端送來的價格或保額（鐵則 1）
- 不存旅客姓名、身分證
- 180 天沒活動的記錄在 backend 啟動時清除
- 匿名統計只存去識別的聚合（方案與次數），不留 `owner_id`
- 未來換 LINE 登入只換「怎麼得到 owner_id」，現在不做

## 步驟

### 1. 資料表

`selected_plan` 繼承 `BaseTable`，欄位照原型規格：`owner_id`、`plan_id`、公司、商品、報價快照（天數、年齡、保額、價格、費率表有效期）、`last_active_at`。照 Schema 變更流程產生 migration。

完成條件：`make migrate` 成功；`owner_id` 有索引。

### 2. API

| 路徑 | 用途 |
| --- | --- |
| `POST /api/v1/selections` | 輸入 `session_id` 與費率表代碼，存快照 |
| `GET /api/v1/selections` | 我的選擇 |
| `DELETE /api/v1/my-data` | 刪除我的所有資料，回刪除筆數 |

token 缺少或格式不對回 400；session 沒有推薦結果或費率表不在推薦裡回 404。沿用限流與存取碼。

完成條件：移植 `tests/test_selections.py`，加上「前端送價格會被忽略」「別人的 token 查不到我的資料」「180 天清除」的測試，全部通過。

### 3. 前端

推薦卡片的「選這個」、我的選擇頁、刪除我的所有資料（要再確認一次）。token 讀寫 localStorage 時包 try/catch，讀不到就產生新的。

完成條件：`VITE_MOCK=true` 下選擇、查看、刪除都能操作；e2e 測選擇後在我的選擇頁看到它。
