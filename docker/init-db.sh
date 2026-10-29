#!/bin/bash
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	SELECT 'CREATE DATABASE arbiterforge_test'
	WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'arbiterforge_test')\gexec
EOSQL
