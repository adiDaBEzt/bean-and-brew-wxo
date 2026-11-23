#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Credentials stay in the Python process and the authenticated API request.
"$ROOT/venv/bin/python" - "$ROOT" <<'PY'
import sys
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from dotenv import dotenv_values
from ibm_watsonx_orchestrate.agent_builder.connections.types import (
    ConnectionConfiguration,
    ConnectionEnvironment,
    ConnectionPreference,
    ConnectionSecurityScheme,
)
from ibm_watsonx_orchestrate.cli.config import (
    Config,
    ENVIRONMENTS_SECTION_HEADER,
    ENV_WXO_URL_OPT,
)
from ibm_watsonx_orchestrate.client.connections import get_connections_client
from requests import RequestException

root = Path(sys.argv[1])
settings = dotenv_values(root / '.env')
account = settings.get('SNOWFLAKE_ACCOUNT') or ''
if not account or account == 'your-account-id':
    raise SystemExit('Set SNOWFLAKE_ACCOUNT in .env before configuring connections.')

adk_config = Config()
active_config = adk_config.read(ENVIRONMENTS_SECTION_HEADER, adk_config.get_active_env()) or {}
active_url = active_config.get(ENV_WXO_URL_OPT)
expected_url = settings.get('WXO_URL') or ''
if not expected_url.startswith('https://') or not active_url or active_url.rstrip('/') != expected_url.rstrip('/'):
    raise SystemExit('Activate the Orchestrate environment whose service instance URL matches WXO_URL in .env.')

role_keys = {}
for role in ('barista', 'manager', 'regional', 'finance', 'hr'):
    path = root / 'snowflake' / 'keys' / f'{role}.p8'
    try:
        pem = path.read_text()
        load_pem_private_key(pem.encode(), password=None)
    except (OSError, ValueError, TypeError):
        raise SystemExit(f'Run the Snowflake bootstrap first. Expected an unencrypted private key at snowflake/keys/{role}.p8.') from None
    role_keys[role] = pem

client = get_connections_client()
for role, pem in role_keys.items():
    app_id = f'bb_sf_{role}'
    action = 'find connection'
    try:
        if client.get(app_id) is None:
            action = 'create connection'
            client.create({'app_id': app_id})
        for environment in ConnectionEnvironment:
            action = f'configure {environment}'
            current = client.get_config(app_id, environment)
            config = ConnectionConfiguration(
                app_id=app_id,
                environment=environment,
                preference=ConnectionPreference.TEAM,
                security_scheme=ConnectionSecurityScheme.KEY_VALUE,
            )
            if current is None:
                client.create_config(app_id, config.model_dump())
            elif current.security_scheme != config.security_scheme or current.preference != config.preference:
                raise SystemExit(f'{app_id} already has an incompatible {environment} configuration. Review it in Orchestrate before retrying.')

            action = f'set {environment} credentials'
            payload = {'runtime_credentials': {'account': account, 'user': f'BB_{role.upper()}_SVC', 'private_key': pem}}
            if client.get_credentials(app_id, environment, use_app_credentials=False):
                client.update_credentials(app_id, environment, payload, use_app_credentials=False)
            else:
                client.create_credentials(app_id, environment, payload, use_app_credentials=False)
            print(f'{app_id} {environment}: configured')
    except RequestException as error:
        status = f'HTTP {error.response.status_code}' if error.response is not None else type(error).__name__
        raise SystemExit(f'{app_id}: could not {action} ({status}). Check the active environment and permissions.') from None
PY

"$ROOT/venv/bin/orchestrate" tools import --kind python --safe \
  --file "$ROOT/wxo/tools/bb_tools.py" --requirements-file "$ROOT/wxo/tools/requirements.txt" \
  --app-id bb_sf_barista --app-id bb_sf_manager --app-id bb_sf_regional \
  --app-id bb_sf_finance --app-id bb_sf_hr
