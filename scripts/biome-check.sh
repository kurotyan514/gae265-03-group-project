#!/usr/bin/env bash
# pre-commit 用：對改動到的前端檔案跑 biome check --write。
# pre-commit 傳進來的路徑是相對 repo 根目錄（frontend/src/...），
# Biome 要在 frontend/ 裡跑才讀得到 biome.json，所以先切進去再把前綴拿掉。
set -euo pipefail

cd "$(dirname "$0")/../frontend"
exec pnpm exec biome check --write --no-errors-on-unmatched "${@#frontend/}"
