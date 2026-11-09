#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE не найден" >&2
  exit 1
fi

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    python3 -c "import secrets; print(secrets.token_hex(32))"
  fi
}

is_placeholder() {
  local val="$1"
  [[ -z "$val" ]] \
    || [[ "$val" == change-me* ]] \
    || [[ "$val" == replace-with-* ]] \
    || [[ "$val" == CHANGE_ME* ]] \
    || [[ "$val" == *change-me* ]] \
    || [[ "$val" == *dev-only* ]]
}

get_var() {
  local key="$1"
  local line
  line=$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 || true)
  [[ -z "$line" ]] && { echo ""; return; }
  echo "${line#*=}"
}

set_var() {
  local key="$1"
  local val="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    local esc
    esc=$(printf '%s' "$val" | sed -e 's/[\/&]/\\&/g')
    sed -i -E "s|^${key}=.*|${key}=${esc}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >>"$ENV_FILE"
  fi
}

POSTGRES_USER=$(get_var POSTGRES_USER); POSTGRES_USER=${POSTGRES_USER:-arbiterforge}
POSTGRES_DB=$(get_var POSTGRES_DB); POSTGRES_DB=${POSTGRES_DB:-arbiterforge}

POSTGRES_PASSWORD=$(get_var POSTGRES_PASSWORD)
if is_placeholder "$POSTGRES_PASSWORD"; then
  POSTGRES_PASSWORD=$(rand_hex)
  set_var POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
fi

REDIS_PASSWORD=$(get_var REDIS_PASSWORD)
if is_placeholder "$REDIS_PASSWORD"; then
  REDIS_PASSWORD=$(rand_hex)
  set_var REDIS_PASSWORD "$REDIS_PASSWORD"
fi

for key in ARBITERFORGE_TOKEN_SECRET ARBITERFORGE_AUDIT_HMAC_SECRET; do
  val=$(get_var "$key")
  if is_placeholder "$val"; then
    set_var "$key" "$(rand_hex)"
  fi
done

set_var ARBITERFORGE_DATABASE_URL \
  "postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
set_var ARBITERFORGE_REDIS_URL \
  "redis://:${REDIS_PASSWORD}@redis:6379/0"
set_var ARBITERFORGE_TEST_DATABASE_URL \
  "postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/arbiterforge_test"
set_var ARBITERFORGE_TEST_REDIS_URL \
  "redis://:${REDIS_PASSWORD}@redis:6379/1"

echo "Секреты сгенерированы в $ENV_FILE (значения не выводятся)"
