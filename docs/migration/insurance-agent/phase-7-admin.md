# 第 7 階段：後台（唯讀）

目標：營運者在後台檢視條文庫、費率表、檢索結果與選定統計。GLOSSARY 的後台包含「輸入與維護保險商品」，這一階段只做檢視，編輯功能另開 spec。

依據：原型 `admin/app.py` 的分頁：總覽、條款段落、費率表、檢索測試、選定統計。切塊預覽不移植（現在一條條文就是一段）。

## 步驟

### 1. 存取控制

依 D7：設定 `ADMIN_TOKEN`，後台 API 一律檢查 `X-Admin-Token` 標頭，用固定時間比對；沒設 `ADMIN_TOKEN` 時後台 API 全部回 404。

完成條件：沒帶、帶錯、沒設定三種情況都有測試。

### 2. 後台 API

放在 `/api/v1/admin/`：

| 路徑 | 內容 |
| --- | --- |
| `GET overview` | 險種數、條文數、向量數（依模型）、費率表數、選定記錄數 |
| `GET rates`、`GET rates/{table_id}` | 費率表清單、缺價格的格數、單一費率表內容與原表備註 |
| `POST search` | 混合檢索，額外回向量與關鍵字各自的排名與分數 |
| `GET stats` | 選定統計（方案與次數，不含 `owner_id`） |

條文清單直接用第 2 階段的 `/api/v1/insurances` 路由。

完成條件：移植 `tests/test_admin.py` 對應的案例，全部通過。

### 3. 前端

`frontend/src/routes/admin/`：第一次進入輸入 token（存 sessionStorage），之後每個請求帶上。一般頁面不放後台入口。

完成條件：`VITE_MOCK=true` 下五個分頁都有畫面。
