#!/usr/bin/env bash
# 開發環境健康檢查（make doctor）：每項 PASS／FAIL，FAIL 附修復提示，任一 FAIL 以非 0 結束。
# macOS 內建 bash 3.2 也要能跑：不用 mapfile、associative array；sed 只用 -nE（BSD／GNU 通用）。
# docker compose 會讀 COMPOSE_PROJECT_NAME、*_PORT 等環境變數與 .env，這裡的檢查一律透過 compose 取得。
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

fails=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fails=$((fails + 1)); }

# 取出工具版本號（只要數字部分）
version_of() {
  case "$1" in
    python) uv run --no-sync python -c 'import platform; print(platform.python_version())' 2>/dev/null ;;
    node) node -v 2>/dev/null | sed 's/^v//' ;;
    pnpm) pnpm -v 2>/dev/null ;;
    uv) uv --version 2>/dev/null | sed -nE 's/^uv ([0-9.]+).*/\1/p' ;;
    *) "$1" --version 2>/dev/null | sed -nE 's/[^0-9]*([0-9][0-9.]*).*/\1/p' ;;
  esac
}

echo "工具鏈（對照 mise.toml）"
if command -v mise >/dev/null 2>&1; then
  pass "mise 已安裝"
else
  fail "mise 未安裝 → 見 https://mise.jdx.dev/getting-started.html，並在 shell 啟用 mise activate"
fi
# mise.toml 寫的是版本前綴（例如 node = "24"），實際版本以此開頭即可
while read -r tool expected; do
  actual=$(version_of "$tool")
  if [[ -n "$actual" && ( "$actual" == "$expected" || "$actual" == "$expected".* ) ]]; then
    pass "$tool $actual"
  else
    fail "$tool 版本應為 ${expected}.x（目前：${actual:-未安裝}）→ mise install，並確認 shell 已啟用 mise"
  fi
done < <(sed -nE 's/^([a-z0-9_-]+) = "([^"]+)"$/\1 \2/p' mise.toml)

echo "設定"
if [[ ! -f .env ]]; then
  fail ".env 不存在 → cp .env.example .env，再依 LLM_PROVIDER 填必填項"
elif err=$(uv run --no-sync python -c 'import app.core.config' 2>&1); then
  pass ".env 必填項齊全（LLM_PROVIDER=$(uv run --no-sync python -c 'from app.core.config import settings; print(settings.LLM_PROVIDER)' 2>/dev/null)）"
elif [[ "$err" == *ModuleNotFoundError* ]]; then
  fail "Python 依賴未安裝，無法檢查 .env → make install"
else
  # 只印驗證訊息那行；Settings 設了 hide_input_in_errors，不會帶出密鑰
  msg=$(printf '%s\n' "$err" | sed -nE 's/^  (Value error, )?(.*) \[type=.*/\2/p' | head -n 1)
  fail ".env 設定有誤：${msg:-$(printf '%s\n' "$err" | tail -n 1)} → 對照 .env.example 修正 .env"
fi

echo "Docker 與服務"
if ! docker info >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  fail "Docker 未安裝或未啟動 → 安裝並開啟 Docker Desktop（WSL2 需在設定啟用 WSL integration）"
else
  pass "Docker 已啟動"
  for svc in $(docker compose config --services 2>/dev/null); do
    # 有 healthcheck 的看 Health，沒有的看 State
    read -r state health <<<"$(docker compose ps --format '{{.State}} {{.Health}}' "$svc" 2>/dev/null)"
    if [[ "${health:-$state}" == "healthy" || ( -z "${health:-}" && "${state:-}" == "running" ) ]]; then
      pass "$svc ${health:-$state}"
    else
      fail "$svc 狀態：${health:-${state:-未啟動}} → make up（已啟動則 make logs s=$svc）"
    fi
  done

  backend_addr=$(docker compose port backend 8000 2>/dev/null)
  body=""
  [[ -n "$backend_addr" ]] && body=$(curl -sS -m 5 "http://localhost:${backend_addr##*:}/api/v1/health" 2>/dev/null)
  if [[ "$body" == *'"status":"ok"'* ]]; then
    pass "/api/v1/health 正常"
  else
    fail "/api/v1/health 失敗${body:+：$body} → make up；已啟動則 make logs s=backend"
  fi

  # 在 db 容器內用容器自己的 POSTGRES_USER／POSTGRES_DB 查詢
  # shellcheck disable=SC2016 # 變數要在容器內展開
  vector=$(docker compose exec -T db sh -c \
    'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT extversion FROM pg_extension WHERE extname = '\''vector'\''"' 2>/dev/null)
  if [[ -n "$vector" ]]; then
    pass "pgvector $vector"
  else
    fail "開發資料庫沒有 pgvector extension → make up；已啟動則 make db-reset"
  fi

  # 在 backend 容器內檢查，才能同時驗證容器到供應商的連線（例如 host.docker.internal 的 Ollama）。
  # 只印供應商、HTTP 狀態碼或例外類別，不印例外訊息（可能夾帶部分 key）。
  if llm=$(docker compose exec -T backend python - 2>/dev/null <<'PY'
import json
import sys
import urllib.error
import urllib.request

from app.core.config import settings as s


def bail(msg):
    print(msg)
    sys.exit(1)


p = s.LLM_PROVIDER
try:
    if p == "ollama":
        with urllib.request.urlopen(f"{s.OLLAMA_BASE_URL}/api/tags", timeout=5) as r:
            names = {m["name"] for m in json.load(r)["models"]}
        want = (s.OLLAMA_CHAT_MODEL, s.OLLAMA_EMBEDDING_MODEL)
        missing = [m for m in want if m not in names and f"{m}:latest" not in names]
        if missing:
            bail(f"Ollama 沒有 model：{', '.join(missing)} → ollama pull <model>，或改 .env 的 OLLAMA_*_MODEL")
    elif p == "openai":
        key = s.OPENAI_API_KEY.get_secret_value() if s.OPENAI_API_KEY else ""
        req = urllib.request.Request(
            f"https://api.openai.com/v1/models/{s.OPENAI_CHAT_MODEL}",
            headers={"Authorization": f"Bearer {key}"},
        )
        urllib.request.urlopen(req, timeout=10).close()  # 免費：只查 model
    elif p == "azure_openai":
        from app.core.llm import get_embeddings

        get_embeddings().embed_query("ping")  # 單 token embedding，成本可忽略
    else:
        bail(f"LLM_PROVIDER={p} 只給測試用 → .env 改成 azure_openai、openai 或 ollama")
except urllib.error.HTTPError as e:
    bail(f"{p} 回應 HTTP {e.code}（401／403 = key 錯，404 = model／deployment 名稱或 endpoint 錯）")
except Exception as e:
    code = getattr(e, "status_code", "")
    bail(f"{p} 連線失敗：{type(e).__name__} {code}（401 = key 錯，404 = deployment 名稱錯，ConnectionError／URLError = endpoint 錯或服務沒開（Ollama：ollama serve））")
print(p)
PY
  ); then
    pass "LLM 供應商可連線（$llm）"
  elif [[ -z "$llm" ]]; then
    fail "無法在 backend 容器內檢查 LLM 供應商 → make up；已啟動則 make logs s=backend"
  else
    fail "$llm"
  fi
fi

echo
if ((fails > 0)); then
  echo "$fails 項 FAIL"
  exit 1
fi
echo "環境正常"
