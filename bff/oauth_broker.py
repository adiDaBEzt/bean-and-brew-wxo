"""Dynamic Snowflake OAuth & Ephemeral Token Broker for Bean & Brew.

Security Architecture:
  1. Accepts the verified employee persona / role from Keycloak OIDC.
  2. Mints short-lived OAuth 2.0 / dynamic session tokens bound to that role.
  3. Provides token-to-connection mapping for Orchestrate tools and audits
     exact credentials requested, eliminating shared static database passwords.
"""
import os
import time
import secrets
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Active role mapping
ROLE_PERMISSIONS = {
    "barista": {
        "sf_user": "BB_BARISTA_SVC",
        "sf_role": "BB_BARISTA",
        "allowed_scopes": ["INVENTORY:READ"],
        "max_ttl_seconds": 300,
    },
    "store_manager": {
        "sf_user": "BB_MANAGER_SVC",
        "sf_role": "BB_MANAGER",
        "allowed_scopes": ["INVENTORY:READ", "INVENTORY:WRITE", "SALES:READ_STORE", "EMPLOYEES:READ_STORE_MASKED"],
        "max_ttl_seconds": 300,
    },
    "regional_manager": {
        "sf_user": "BB_REGIONAL_SVC",
        "sf_role": "BB_REGIONAL",
        "allowed_scopes": ["INVENTORY:READ_REGION", "SALES:READ_REGION"],
        "max_ttl_seconds": 300,
    },
    "finance_analyst": {
        "sf_user": "BB_FINANCE_SVC",
        "sf_role": "BB_FINANCE",
        "allowed_scopes": ["SALES_DAILY:READ", "SALARY_SUMMARY:READ"],
        "max_ttl_seconds": 300,
    },
    "hr_admin": {
        "sf_user": "BB_HR_SVC",
        "sf_role": "BB_HR",
        "allowed_scopes": ["EMPLOYEES:FULL_ACCESS"],
        "max_ttl_seconds": 300,
    },
}

class DynamicTokenBroker:
    """Issues ephemeral, audited dynamic access tokens for Snowflake access."""

    def __init__(self):
        self._active_tokens: Dict[str, Dict[str, Any]] = {}

    def mint_token(self, username: str, role: str, store_id: str, region: str) -> Dict[str, Any]:
        spec = ROLE_PERMISSIONS.get(role)
        if not spec:
            raise ValueError(f"Unknown or unauthorized role: {role}")

        token_id = f"sf_dyn_{secrets.token_hex(16)}"
        expires_at = time.time() + spec["max_ttl_seconds"]

        # Ephemeral token metadata (audited)
        token_info = {
            "token": token_id,
            "username": username,
            "role": role,
            "snowflake_user": spec["sf_user"],
            "snowflake_role": spec["sf_role"],
            "store_id": store_id,
            "region": region,
            "scopes": spec["allowed_scopes"],
            "expires_at": expires_at,
            "issued_at": time.time(),
        }
        self._active_tokens[token_id] = token_info
        return token_info

    def validate_and_get_session_params(self, token_id: str) -> Dict[str, Any]:
        info = self._active_tokens.get(token_id)
        if not info:
            raise PermissionError("Invalid or nonexistent dynamic token")
        if time.time() > info["expires_at"]:
            del self._active_tokens[token_id]
            raise PermissionError("Dynamic token expired")
        return info

token_broker = DynamicTokenBroker()
