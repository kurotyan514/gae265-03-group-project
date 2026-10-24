---
status: accepted
---

# 正式環境部署在單台 Azure B2s VM，用 docker compose

正式環境是一台 Azure B2s VM（2 vCPU、4 GB RAM），用 `compose.prod.yaml` 跑 backend、Postgres 與 Caddy（提供前端靜態檔、把 `/api` 轉給 backend、Let's Encrypt 自動 HTTPS），網域用 VM 免費的 `<名稱>.<區域>.cloudapp.azure.com`。這是 demo 等級的 MVP，不是正式產品：開發與正式環境共用同一套 compose 與多階段 Dockerfile（`dev`／`prod` target），組員只需要理解一套東西；不 demo 時可以把 VM 停機省錢。

## Considered Options

- **Azure Container Apps**：直接跑 image、可縮到零，但不適合跑資料庫，等於要另開 Flexible Server，多一個服務與一筆費用。
- **App Service for Containers**：同樣要另外處理資料庫，多容器支援不如 compose 直接。
- **單台 VM + docker compose**（採用）。

## Consequences

- LLM 不能跑在 VM 上（4 GB 放不下），正式環境的模型與 embedding 一律走 Azure OpenAI。
- 部署先手動：`make deploy` SSH 到 VM 執行 `git pull` 與 `docker compose -f compose.prod.yaml up -d --build`。之後的 CD（GitHub Actions 觸發同一套指令，或改成推 GHCR、VM 只 `pull`）是在這之上加，不改 compose。
- 正式環境的 secrets 只放在 VM 上的 `.env`，不用 Key Vault。
- 要升級成正式產品時（高可用、備份、自動擴展），這份決定就該重新評估。
