#!/bin/bash
# 只在資料庫 volume 初次建立時執行：建立測試資料庫，並在開發與測試資料庫安裝 pgvector
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE DATABASE "$POSTGRES_TEST_DB";
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_TEST_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
