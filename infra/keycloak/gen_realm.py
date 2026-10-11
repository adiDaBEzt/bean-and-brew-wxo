"""Generate the Keycloak realm import file for Bean & Brew.

Secrets (client secret, demo user password) come from ../../.env and are never committed:
the generated realm-bean-brew.json is git-ignored. Run: venv/bin/python infra/keycloak/gen_realm.py
"""
import json
import pathlib
import re
import secrets

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"


def env_get_or_create(key, value_fn):
    text = ENV_FILE.read_text()
    m = re.search(rf"^{key}=(.*)$", text, flags=re.M)
    if m and m.group(1):
        return m.group(1)
    v = value_fn()
    ENV_FILE.write_text(text.rstrip("\n") + f"\n{key}={v}\n")
    return v


CLIENT_SECRET = env_get_or_create("KEYCLOAK_CLIENT_SECRET", lambda: secrets.token_urlsafe(24))
USER_PASSWORD = env_get_or_create("DEMO_USER_PASSWORD", lambda: "Brew-" + secrets.token_urlsafe(9))

ROLES = ["barista", "store_manager", "regional_manager", "finance_analyst", "hr_admin"]
USERS = [
    # username, first, last, role, store_id, region
    ("maya", "Maya", "Chen", "barista", "S01", "NORTH"),
    ("sam", "Sam", "Rivera", "store_manager", "S01", "NORTH"),
    ("priya", "Priya", "Nair", "regional_manager", "HQ", "NORTH"),
    ("felix", "Felix", "Weber", "finance_analyst", "HQ", "HQ"),
    ("hana", "Hana", "Sato", "hr_admin", "HQ", "HQ"),
]


def attr_mapper(attr):
    return {"name": attr, "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {"user.attribute": attr, "claim.name": attr, "jsonType.label": "String",
                       "id.token.claim": "true", "access.token.claim": "true", "userinfo.token.claim": "true"}}


realm = {
    "realm": "bean-brew",
    "enabled": True,
    "displayName": "Bean & Brew",
    "sslRequired": "none",
    "registrationAllowed": False,
    "loginWithEmailAllowed": True,
    "roles": {"realm": [{"name": r, "description": f"Bean & Brew {r}"} for r in ROLES]},
    "clients": [{
        "clientId": "bb-web",
        "name": "Bean & Brew Web",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "secret": CLIENT_SECRET,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": False,
        "redirectUris": ["http://localhost:8000/auth/callback", "http://localhost:5173/*"],
        "webOrigins": ["http://localhost:5173", "http://localhost:8000"],
        "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "http://localhost:5173/*"},
        "defaultClientScopes": ["web-origins", "profile", "email", "roles"],
        "protocolMappers": [
            {"name": "realm-roles", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-realm-role-mapper",
             "config": {"claim.name": "roles", "multivalued": "true", "jsonType.label": "String",
                        "id.token.claim": "true", "access.token.claim": "true", "userinfo.token.claim": "true"}},
            attr_mapper("store_id"), attr_mapper("region"),
        ],
    }],
    "users": [
        {
            "username": u, "enabled": True, "emailVerified": True,
            "firstName": f, "lastName": l, "email": f"{f.lower()}.{l.lower()}@beanandbrew.example",
            "attributes": {"store_id": [s], "region": [rg]},
            "realmRoles": [r],
            "credentials": [{"type": "password", "value": USER_PASSWORD, "temporary": False}],
        }
        for (u, f, l, r, s, rg) in USERS
    ],
}

out = pathlib.Path(__file__).resolve().parent / "realm-bean-brew.json"
out.write_text(json.dumps(realm, indent=2))
print(f"wrote {out} ({len(USERS)} users, {len(ROLES)} roles)")
