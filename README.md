# gae265_03_group_project

根據旅行規劃推薦旅遊保險、並依條款回答問題的 SPA。名詞定義見 [GLOSSARY.md](GLOSSARY.md)。

## 開發環境

### 1. 安裝工具

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)（含 compose）
- [mise](https://mise.jdx.dev/getting-started.html)：管理 Python、Node、pnpm、uv 的版本（見 `mise.toml`）。安裝後依官方說明在 shell 設定檔加上 `mise activate`，重開終端機

**Windows 組員一律用 WSL2**：

1. 安裝 WSL2 與 Ubuntu（PowerShell：`wsl --install`），之後所有指令都在 WSL 的終端機裡執行
2. Docker Desktop 設定 →「Resources」→「WSL integration」啟用你的 Ubuntu
3. repo clone 在 WSL 檔案系統（例如 `~/projects/`），不要放在 `/mnt/c/...`：跨檔案系統的檔案監看與 I/O 很慢，`make up` 的熱重載會失效
4. mise 裝在 WSL 裡（照 Linux 的安裝方式）

### 2. 啟動

在 repo 根目錄：

```bash
mise install          # 安裝 mise.toml 指定的工具版本
cp .env.example .env  # 依下一節設定 LLM 供應商
make install          # uv sync、pnpm install、pre-commit install
make up               # 啟動所有服務並監看程式碼變動（前景執行，Ctrl+C 停止）
make doctor           # 另開一個終端機執行，全部 PASS 才算完成
```

`make doctor` 的 FAIL 會附修法（例如 `make up` 沒開、`.env` 缺設定）。服務啟動後：

| 服務 | 網址 |
| --- | --- |
| 前端 | http://localhost:5173 |
| backend（API docs） | http://localhost:8000/docs |
| health | http://localhost:8000/api/v1/health |
| pgAdmin | http://localhost:5050 |
| PostgreSQL | localhost:5432（`gae265_03_group_project`、`gae265_03_group_project_test`） |

port 跟本機其他服務衝突時，改 `.env` 的 `POSTGRES_PORT`、`PGADMIN_PORT`、`BACKEND_PORT`、`FRONTEND_PORT`。

### 3. LLM 供應商

`.env` 的 `LLM_PROVIDER` 決定 chat 與 embedding 的供應商，缺必填設定時 backend 啟動即失敗：

- `azure_openai`（預設）：開發用的 Azure OpenAI endpoint、key 與 deployment 名稱**向組員私下取得**，填進 `.env` 的 `AZURE_OPENAI_*`；不要貼在 issue、PR 或聊天群組
- `ollama`：還沒拿到 key 時用本機模型。安裝 [Ollama](https://ollama.com/) 後 `ollama pull llama3.2` 與 `ollama pull nomic-embed-text`（或改 `.env` 的 `OLLAMA_CHAT_MODEL`、`OLLAMA_EMBEDDING_MODEL`），`.env` 設 `LLM_PROVIDER=ollama`
- `openai`：有自己的 OpenAI key 時可用，填 `OPENAI_API_KEY`

改 `.env` 後重新 `make up` 讓 backend 讀到新設定。測試一律用假的供應商，不需要任何 key。

### 常用指令

`make help` 列出全部。

| 指令 | 用途 |
| --- | --- |
| `make up`／`make down` | 啟動／停止服務 |
| `make logs s=backend` | 看單一服務的 log |
| `make test` | 後端測試（只連 `_test` 資料庫，需先 `make up` 或至少啟動 db） |
| `make e2e` | Playwright 冒煙測試（需先 `make up`） |
| `make lint`／`make format` | lint 與型別檢查／自動修正格式 |
| `make migration m="..."` → `make migrate` | 產生並套用 migration |
| `make client` | 改了 API 後重新產生前端 API client |
| `make db-reset` | 清空並重建開發資料庫 |

前端假資料模式（不需要後端）：`cd frontend && VITE_MOCK=true pnpm dev`。

## 部署到 Azure

正式環境是一台 Azure B2s VM，用 `compose.prod.yaml` 跑 Postgres、backend 與 Caddy（自動 HTTPS），架構與取捨見 [docs/adr/0001](docs/adr/0001-single-vm-docker-compose-deploy.md)。以下指令用 [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)，先 `az login`；用 Azure Portal 操作也可以，設定值相同。

### 1. 建立 Azure OpenAI deployment

正式環境的 LLM 與 embedding 一律走 Azure OpenAI（VM 跑不動本機模型）。在 Azure OpenAI 資源中各建立一個 chat model 與 embedding model 的 deployment，記下：

- Endpoint（`https://<資源名稱>.openai.azure.com/`）與 API key
- Chat deployment 名稱、embedding deployment 名稱

### 2. 建立 VM

```bash
RG=gae265-rg
LOCATION=japaneast          # 區域，也是網址的 <區域>
DNS_NAME=gae265-demo        # 網址的 <名稱>，該區域內不能重複

az group create -n $RG -l $LOCATION
az vm create -g $RG -n gae265-vm \
  --image Ubuntu2404 --size Standard_B2s \
  --admin-username azureuser --generate-ssh-keys \
  --public-ip-sku Standard --public-ip-address-dns-name $DNS_NAME
az vm open-port -g $RG -n gae265-vm --port 80,443 --priority 900
```

- `--public-ip-address-dns-name` 就是 DNS 名稱標籤，網址是 `$DNS_NAME.$LOCATION.cloudapp.azure.com`（已建好的 VM 到 Portal 的公用 IP →「設定」→「DNS 名稱標籤」設定）。
- 80 要開：Let's Encrypt 用它驗證網域；22（SSH）`az vm create` 預設已開。
- 不 demo 時 `az vm deallocate -g $RG -n gae265-vm` 停機省錢，要用時 `az vm start`；網址不變。

### 3. VM 初次設定

```bash
ssh azureuser@$DNS_NAME.$LOCATION.cloudapp.azure.com

# 安裝 docker（含 compose plugin），讓目前使用者免 sudo
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit   # 重新登入讓群組生效
```

重新 SSH 進去後：

```bash
git clone https://github.com/kurotyan514/gae265-03-group-project.git
cd gae265-03-group-project
cp .env.prod.example .env
nano .env
```

`.env` 依 `.env.prod.example` 的註解填寫，只存在 VM 上、不進 git：

- `DOMAIN=<名稱>.<區域>.cloudapp.azure.com`
- `POSTGRES_PASSWORD`：強密碼（必填）
- `LLM_PROVIDER=azure_openai`，`AZURE_OPENAI_ENDPOINT`、`AZURE_OPENAI_API_KEY`、`AZURE_OPENAI_CHAT_DEPLOYMENT`、`AZURE_OPENAI_EMBEDDING_DEPLOYMENT` 填步驟 1 的值（缺任一項 backend 啟動即失敗）

repo 若是 private，clone 前先在 VM 上 `ssh-keygen` 並把公鑰加到 GitHub repo 的 Deploy keys（唯讀），改用 SSH 網址 clone。

### 4. 首次啟動

在 VM 的 repo 根目錄：

```bash
docker compose -f compose.prod.yaml up -d --build
docker compose -f compose.prod.yaml ps    # db、backend、caddy 都是 running／healthy
```

backend 啟動時會自動套用 migration。Caddy 第一次啟動會申請憑證，log 可用 `docker compose -f compose.prod.yaml logs -f caddy` 看。

### 5. 之後的部署

把要上線的變更 merge 到 `main` 後，在本機 repo 根目錄執行：

```bash
make deploy DEPLOY_HOST=azureuser@<名稱>.<區域>.cloudapp.azure.com
```

它會 SSH 到 VM，在 `~/gae265-03-group-project`（VM 上 repo 位置不同時加 `DEPLOY_DIR=<路徑>`）切到 `main` 並 `git pull --ff-only origin main`（不論 VM 上目前在哪個 branch，一律部署 `main`；VM 上有本地修改或分岔時會中止，要先進 VM 處理），再執行 `docker compose -f compose.prod.yaml up -d --build`。`DEPLOY_HOST`／`DEPLOY_DIR` 從命令列或環境變數傳入（例如在 shell 設定檔 `export DEPLOY_HOST=...`），不寫在 `.env`。

### 6. 驗收

用瀏覽器開 `https://<名稱>.<區域>.cloudapp.azure.com`：網址列顯示憑證有效，首頁顯示健康狀態。

注意：不要 `docker compose -f compose.prod.yaml down -v`，會刪掉資料庫與憑證（重新申請受 Let's Encrypt 頻率限制）。
