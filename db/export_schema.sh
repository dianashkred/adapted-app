#!/bin/bash
# Regenerates db/schema.sql (DDL of the whole database) FROM THE MIGRATIONS — never edit schema.sql by hand.
#   1. docker compose up -d db && (cd backend && alembic upgrade head)
#   2. bash db/export_schema.sh
set -euo pipefail
cd "$(dirname "$0")/.."
{
  echo "-- AdaptED — DDL of the database (PostgreSQL 16 + pgvector)."
  echo "-- GENERATED from the Alembic migrations by db/export_schema.sh on $(date -u +%Y-%m-%d). Do not edit by hand."
  echo "-- Prerequisites: roles from db/init/01-roles-and-databases.sh; extension: CREATE EXTENSION vector;"
  echo
  docker compose exec -T db pg_dump -U "${POSTGRES_USER:-postgres}" -d adapted --schema-only --no-owner \
    --schema=public --schema=analytics -T alembic_version \
    | sed "s/^CREATE SCHEMA public;/CREATE SCHEMA IF NOT EXISTS public;/"
} > db/schema.sql
echo "db/schema.sql updated ($(grep -c 'CREATE TABLE' db/schema.sql) tables)"
