---
status: accepted
---

# 條款上傳用 BackgroundTasks 跑 ingest agent，事件寫進資料庫並以 SSE 推送

上傳條款 PDF 後，後端在背景依序執行：讀取 → 判斷是否為條款 → 切 chunk → 驗證 → 算 embedding → 入庫。每個動作寫成一筆 `ingest_event`（立刻 commit），`GET /ingest/jobs/{id}/events` 以 SSE 讀這張表推給前端。承接 [ADR-0003](0003-no-background-worker-yet.md)：仍用 `BackgroundTasks`，不引入 Celery／Redis。

「是不是條款」由規則（切得出足夠的「第N條」）與 LLM 兩者都通過才算；LLM 只回答是／否與理由，不產生數字（[ADR-0004](0004-llm-never-produces-numbers.md)）。端點只在非 production 註冊，與 `/dev` 一致。

## Considered Options

- **事件寫資料庫 + SSE**（採用）：重整頁面或晚點連線都能重放已發生的事件；多個瀏覽器分頁看到同樣的進度。代價是 SSE 路由以 0.5 秒輪詢資料表。
- **記憶體內的 queue 直接推 SSE**：即時、不用輪詢，但重整或重連就看不到先前的步驟，也無法留下歷史。
- **前端輪詢 API**：最簡單，但進度不即時。

## 已知限制

- backend 重啟會中斷背景工作：啟動時（非 production）把殘留的 `running` 標為 `failed`。
- 掃描檔（沒有文字層）會被拒絕；OCR 上線時依 ADR-0003 的條件重新評估 Celery。
- 上傳會 upsert 正式表，同一險種代碼重傳會取代該險種的條文（UUID 保留）。
