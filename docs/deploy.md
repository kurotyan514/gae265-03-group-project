# 部署（GitHub CD → GHCR → Azure VM）

決策見 [ADR-0001](adr/0001-single-vm-docker-compose-deploy.md)。

## 流程

推 `v*` tag（或到 Actions 頁面手動執行 Deploy，選 main 或某個 tag）：

1. `check`：commit 必須在 main 歷史上，否則失敗（tag 打在未合併分支會被擋）
2. `build`：在 GitHub 打包 `backend`、`caddy`（含前端）推到 `ghcr.io/kurotyan514/gae265-03-group-project-{backend,caddy}:<commit SHA>`；該 SHA 的 image 已存在就跳過
3. `deploy`（Environment `production`）：SSH 進 VM 執行 `make deploy`，再從外部檢查 `https://<網域>/api/v1/health`

連續觸發：打包中的舊版會被取消；正在部署的跑完，排隊的只留最新一次。

```bash
git tag v0.1.0 && git push origin v0.1.0
```

## 首次架設

執行 `scripts/setup-vm.sh`（從 `az login` 開始，每一步先顯示指令、確認後才執行）。精靈會：建 VM（B2s、Ubuntu、`eastasia`，不行改 `japaneast`）、開 22／80／443、設網域與每天台灣時間 23:00 自動關機、產生部署金鑰與 host key，並引導你：

- 裝 Docker、clone repo、從 `.env.prod.example` 建 `.env`
- 到 Google Cloud Console 登記 `${PUBLIC_BASE_URL}/api/v1/auth/google/callback`
- 在 GitHub 建 Environment `production`（deployment 只允許 `main` 與 `v*`，不設 reviewer），放三個 secret：
  - `DEPLOY_HOST`：`user@<名稱>.<區域>.cloudapp.azure.com`
  - `DEPLOY_SSH_KEY`：部署專用私鑰
  - `DEPLOY_KNOWN_HOSTS`：VM 的 host key
- 第一次部署後，把兩個 GHCR package 改成 public（預設 private，VM 才能不登入 pull），再重跑部署
- 匯入 seed（VM 上不能用 `make seed`）：

```bash
IMAGE_TAG=$(git rev-parse HEAD) docker compose -f compose.prod.yaml exec backend python -m app.seed load
# embedding deployment 名稱與匯出時不同：加 --as-model <名稱>
```

`.env` 必須補齊 [integration-plan](integration-plan.md) 列的正式環境必填設定（Google、`TOKEN_ENCRYPTION_KEY`、`ADMIN_EMAILS` 等），缺任何一項 backend 會啟動失敗，部署的 `--wait` 會失敗。

## 回滾

手動部署舊的 tag。GHCR 已有該版 image 就不重新打包。

注意：不會退回 migration。舊程式碼與新資料表結構不相容時，要寫新的 migration 修正，不能直接回滾。

## 本機手動部署（GitHub Actions 不能用時）

```bash
make deploy DEPLOY_HOST=user@<網域> REF=v0.1.0
```

該版 image 必須已由 CD 打包過（`--no-build`，不存在會直接失敗）。

## VM 停機

部署前不會自動開機。VM 關機時部署會 SSH 逾時而失敗；開機後重跑 workflow。

## 在 VM 上手動執行 compose

要自己帶 `IMAGE_TAG`：

```bash
IMAGE_TAG=$(git rev-parse HEAD) docker compose -f compose.prod.yaml ps
```

本機驗證正式環境（不經 GHCR）：`docker compose -f compose.prod.yaml up --build`。
