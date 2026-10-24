#!/bin/bash
# 只在資料庫 volume 初次建立時執行：在主資料庫安裝 pgvector；
# 有設 POSTGRES_TEST_DB（開發環境）時再建立測試資料庫並安裝 pgvector，正式環境不設
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

if [[ -z "${POSTGRES_TEST_DB:-}" ]]; then
  exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE "$POSTGRES_TEST_DB";
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_TEST_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
