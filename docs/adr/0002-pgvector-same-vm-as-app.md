---
status: accepted
---

# 向量用 pgvector，資料庫以容器跑在 app 同一台 VM

保險商品、條款 chunk 與向量都存在同一個 Postgres（pgvector 擴充），開發用 `pgvector/pgvector` image，正式環境也是同一個 image 跑在 [ADR-0001](0001-single-vm-docker-compose-deploy.md) 的 VM 上，不用 Azure Database for PostgreSQL Flexible Server。資料與向量在同一個資料庫，查詢可以直接 join、不用同步兩個系統；放在同一台 VM 省掉 Flexible Server（最便宜的 B1ms 約每月 13–15 美元）的費用與設定。

## Considered Options

- **Azure AI Search 當向量庫**：多一個服務與費用，資料要在兩處同步。
- **Flexible Server**：代管、有自動備份，但多一台與一筆費用，demo 用不到。
- **pgvector 容器跟 app 同一台**（採用）。

## Consequences

- 刻意不做備份：VM 或 volume 壞掉時正式資料會遺失，demo 階段可以接受。
- 之後要搬到 Flexible Server（同樣支援 pgvector）只需改 `DATABASE_URL` 並遷移資料，程式不用動。
