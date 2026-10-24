---
status: accepted
---

# 第一版不放背景工作佇列（Celery／Redis）

第一版沒有 worker、Celery、Flower 與 Redis。後台存檔保險商品時算 embedding 這類較慢的工作，先用 FastAPI 的 `BackgroundTasks` 在同一個 process 裡做，商品只有少量時夠用，也少三個服務。這是刻意的「先不做」，不是漏掉：參考的 soshow 專案有完整的 Celery 架構，但那裡的工作量與這裡不同。

## Considered Options

- **FastAPI `BackgroundTasks`**（採用）：零額外服務；backend 重啟時跑到一半的工作會遺失，也沒有重試與監控。
- **Celery + Redis（+ Flower）**：工作可重試、可監控、可跑很久，worker 可獨立擴充；多三個服務，B2s 的 4 GB 要分給它們。
- **獨立的 CLI 指令**（`make ingest` 之類）：適合一次性的批次匯入；營運者在後台操作時不適用。

## 何時改用 Celery + Redis

出現任一情況時重新評估：

- 條款 PDF 的 OCR 抽取或 LangGraph 解析流程上線，單一工作會跑到數分鐘
- 工作失敗需要自動重試，或需要看到工作進度與歷史
- backend 重啟造成工作遺失已經實際發生且無法接受
