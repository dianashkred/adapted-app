#!/bin/bash
# Runs ONCE, as the superuser, when the Docker volume is created (docker-entrypoint-initdb.d).
# Creates the group roles required by the Database criterion, the login roles and the databases.
# The application never connects as a superuser.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v migrator_pw="$MIGRATOR_DB_PASSWORD" -v app_pw="$APP_DB_PASSWORD" -v analyst_pw="$ANALYST_DB_PASSWORD" <<'SQL'
-- Group roles (NOLOGIN): permissions are granted to them, never to people or services directly.
CREATE ROLE admin NOLOGIN;                       -- owns the schema, runs migrations (DDL)
CREATE ROLE app_read NOLOGIN;                    -- SELECT on application tables
CREATE ROLE app_write NOLOGIN IN ROLE app_read;  -- + INSERT/UPDATE/DELETE, EXECUTE on functions
CREATE ROLE analytics_read NOLOGIN;              -- only the pseudonymised views in schema analytics

-- Login roles (one per service).
CREATE ROLE adapted_migrator LOGIN PASSWORD :'migrator_pw' IN ROLE admin;
CREATE ROLE adapted_app      LOGIN PASSWORD :'app_pw'      IN ROLE app_write;
CREATE ROLE adapted_analyst  LOGIN PASSWORD :'analyst_pw'  IN ROLE analytics_read;

CREATE DATABASE adapted      OWNER admin;
CREATE DATABASE adapted_test OWNER admin;
SQL

for db in adapted adapted_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector needs a superuser to install
ALTER SCHEMA public OWNER TO admin;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE $db FROM PUBLIC;
GRANT CONNECT ON DATABASE $db TO admin, app_read, analytics_read;
SQL
done
