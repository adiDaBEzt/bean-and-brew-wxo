#!/usr/bin/env bash
# Creates one WXO key_value connection per Snowflake role and imports the Python tools.
# Requires: .env loaded, `orchestrate` active env.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a; source "$ROOT/.env"; set +a
O="${ORCHESTRATE:-$ROOT/../venv/bin/orchestrate}"

for r in barista manager regional finance hr; do
  app="bb_sf_${r}"
  up="$(echo "$r" | tr a-z A-Z)"
  pw_var="SNOWFLAKE_BB_${up}_PASSWORD"
  $O connections add --app-id "$app" 2>/dev/null || true
  for env in draft live; do
    $O connections configure --app-id "$app" --env $env --type team --kind key_value 2>/dev/null || true
    $O connections set-credentials --app-id "$app" --env $env \
      -e "account=${SNOWFLAKE_ACCOUNT}" -e "user=BB_${up}_SVC" -e "password=${!pw_var}"
  done
done

APP_ARGS=""
for r in barista manager regional finance hr; do APP_ARGS="$APP_ARGS --app-id bb_sf_$r"; done
$O tools import -k python -f "$ROOT/wxo/tools/bb_tools.py" -r "$ROOT/wxo/tools/requirements.txt" $APP_ARGS
