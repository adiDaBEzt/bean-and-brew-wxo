"""FastAPI Backend-For-Frontend (BFF) with Agent RBAC, Mem0 Long-Term Memory, and Dynamic OAuth Tokens.

Key Capabilities:
  1. Multi-Agent RBAC: Only authorized roles can route to specialized agents (e.g., HR agent restricted to hr_admin).
  2. Mem0 Long-Term Memory: Cross-session semantic memory isolation keyed to user identity.
  3. Dynamic Token Broker: Ephemeral role-scoped credentials issued per session.
  4. watsonx Orchestrate Runs API: Tamper-proof context variable injection.
"""
import os
import pathlib
import time, asyncio
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from pydantic import BaseModel

from bff.memory_manager import record_user_memory, search_user_memories
from bff.oauth_broker import token_broker

ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "bean-brew")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "bb-web")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
DEMO_USER_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "")

WXO_URL = os.getenv("WXO_URL", "")
WXO_API_KEY = os.getenv("WXO_API_KEY", "")

# Registered Agent Catalog
AGENTS_CATALOG = {
    "bb_assistant": {
        "id": "625b0516-9857-4c1f-a854-873e13f3197d",
        "name": "bb_assistant",
        "title": "General Operations Assistant",
        "allowed_roles": ["barista", "store_manager", "regional_manager", "finance_analyst", "hr_admin"],
    },
    "bb_hr_agent": {
        "id": "4dfacfc3-780d-4fae-aabb-fc323a1b4476",
        "name": "bb_hr_agent",
        "title": "HR Operations & Personnel Agent",
        "allowed_roles": ["hr_admin"],
    },
    "bb_finance_agent": {
        "id": "0d3fc642-6016-405e-a0a5-75bb01dc24f5",
        "name": "bb_finance_agent",
        "title": "Financial Analytics & Compensation Agent",
        "allowed_roles": ["finance_analyst"],
    },
}

JWT_SECRET = os.getenv("BFF_JWT_SECRET", "bb-dev-secret-key-38291048123912093")
JWT_ALGORITHM = "HS256"

app = FastAPI(title="Bean & Brew Enterprise BFF API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_iam_token_cache: Dict[str, any] = {"token": None, "expires_at": 0}


async def get_wxo_iam_token() -> str:
    now = time.time()
    if _iam_token_cache["token"] and _iam_token_cache["expires_at"] > now + 60:
        return _iam_token_cache["token"]

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://iam.cloud.ibm.com/identity/token",
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": WXO_API_KEY,
            },
            timeout=15.0,
        )
        if r.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to authenticate with IBM Cloud IAM",
            )
        data = r.json()
        token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        _iam_token_cache["token"] = token
        _iam_token_cache["expires_at"] = now + expires_in
        return token


class LoginRequest(BaseModel):
    username: str
    password: Optional[str] = None


class UserProfile(BaseModel):
    username: str
    email: str
    role: str
    store_id: str
    region: str
    accessible_agents: List[dict]
    dynamic_token: dict


class ChatRequest(BaseModel):
    message: str
    agent_name: Optional[str] = "bb_assistant"
    thread_id: Optional[str] = None


def create_session_token(profile: dict) -> str:
    payload = profile.copy()
    payload["exp"] = int(time.time()) + 86400
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(bb_session: Optional[str] = Cookie(None)) -> dict:
    if not bb_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
    try:
        payload = jwt.decode(bb_session, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")


def get_accessible_agents_for_role(role: str) -> List[dict]:
    accessible = []
    for k, a in AGENTS_CATALOG.items():
        if role in a["allowed_roles"]:
            accessible.append({"name": a["name"], "title": a["title"], "id": a["id"]})
    return accessible


@app.get("/api/auth/me", response_model=UserProfile)
def get_me(user: dict = Depends(get_current_user)):
    role = user.get("role", "")
    accessible = get_accessible_agents_for_role(role)
    dyn_token = token_broker.mint_token(
        username=user.get("username", ""),
        role=role,
        store_id=user.get("store_id", ""),
        region=user.get("region", ""),
    )
    return UserProfile(
        username=user.get("username", ""),
        email=user.get("email", ""),
        role=role,
        store_id=user.get("store_id", ""),
        region=user.get("region", ""),
        accessible_agents=accessible,
        dynamic_token=dyn_token,
    )


@app.post("/api/auth/login")
async def login(req: LoginRequest, response: Response):
    pw = req.password or DEMO_USER_PASSWORD
    token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

    async with httpx.AsyncClient() as client:
        res = await client.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": KEYCLOAK_CLIENT_ID,
                "client_secret": KEYCLOAK_CLIENT_SECRET,
                "username": req.username,
                "password": pw,
                "scope": "openid profile email",
            },
            timeout=10.0,
        )

    if res.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or credentials")

    access_token = res.json()["access_token"]
    claims = jwt.get_unverified_claims(access_token)

    roles = claims.get("roles", [])
    primary_role = roles[0] if isinstance(roles, list) and roles else "barista"

    profile = {
        "username": claims.get("preferred_username", req.username),
        "email": claims.get("email", f"{req.username}@beanandbrew.example"),
        "role": primary_role,
        "store_id": claims.get("store_id", "S01"),
        "region": claims.get("region", "NORTH"),
    }

    session_cookie = create_session_token(profile)
    response.set_cookie(
        key="bb_session",
        value=session_cookie,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    accessible = get_accessible_agents_for_role(primary_role)
    dyn_token = token_broker.mint_token(
        username=profile["username"],
        role=primary_role,
        store_id=profile["store_id"],
        region=profile["region"],
    )
    return {**profile, "accessible_agents": accessible, "dynamic_token": dyn_token}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(key="bb_session")
    return {"status": "logged_out"}


@app.get("/api/memory")
def get_memories(user: dict = Depends(get_current_user)):
    """Retrieve long-term semantic memories stored for the active user via Mem0."""
    user_id = user["username"]
    memories = search_user_memories(user_id=user_id, query="preferences and facts", limit=10)
    return {"user_id": user_id, "memories": memories}


@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    target_agent_name = req.agent_name or "bb_assistant"
    agent_spec = AGENTS_CATALOG.get(target_agent_name)

    if not agent_spec:
        raise HTTPException(status_code=400, detail=f"Agent '{target_agent_name}' does not exist")

    # 1. Multi-Agent Access Control (RBAC check at agent entry)
    if user["role"] not in agent_spec["allowed_roles"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access Denied: Your role '{user['role']}' is not permitted to access agent '{agent_spec['title']}'. Required roles: {agent_spec['allowed_roles']}.",
        )

    # 2. Retrieve relevant long-term memories via Mem0
    user_id = user["username"]
    recalled_memories = search_user_memories(user_id=user_id, query=req.message, limit=3)
    memory_context_str = ""
    if recalled_memories:
        memory_context_str = "\n[Persistent User Long-Term Memory]:\n" + "\n".join(f"- {m}" for m in recalled_memories)

    # 3. Dynamic Ephemeral Token
    dyn_token = token_broker.mint_token(
        username=user["username"],
        role=user["role"],
        store_id=user["store_id"],
        region=user["region"],
    )

    augmented_prompt = req.message
    if memory_context_str:
        augmented_prompt = f"{req.message}\n{memory_context_str}"

    iam_token = await get_wxo_iam_token()
    headers = {
        "Authorization": f"Bearer {iam_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "agent_id": agent_spec["id"],
        "agent_name": agent_spec["name"],
        "message": {
            "role": "user",
            "content": augmented_prompt,
        },
        "context": {
            "bb_role": user["role"],
            "bb_store_id": user["store_id"],
            "bb_region": user["region"],
            "bb_email": user["email"],
            "bb_dynamic_token": dyn_token["token"],
        },
    }
    if req.thread_id:
        payload["thread_id"] = req.thread_id

    async with httpx.AsyncClient() as client:
        run_res = await client.post(
            f"{WXO_URL}/v1/orchestrate/runs",
            headers=headers,
            json=payload,
            timeout=30.0,
        )

        if run_res.status_code != 200:
            raise HTTPException(
                status_code=run_res.status_code,
                detail=f"WXO run start failed: {run_res.text}",
            )

        run_data = run_res.json()
        run_id = run_data.get("run_id")
        thread_id = run_data.get("thread_id")

        for _ in range(60):
            await asyncio.sleep(2)
            status_res = await client.get(
                f"{WXO_URL}/v1/orchestrate/runs/{run_id}",
                headers=headers,
                timeout=15.0,
            )
            if status_res.status_code == 200:
                s_data = status_res.json()
                curr_status = s_data.get("status")
                if curr_status in ["completed", "failed", "cancelled"]:
                    if curr_status != "completed":
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Agent execution {curr_status}: {s_data.get('last_error')}",
                        )
                    msg_obj = s_data.get("result", {}).get("data", {}).get("message", {})
                    content_list = msg_obj.get("content", [])
                    reply_text = "".join([c.get("text", "") for c in content_list if isinstance(c, dict)])

                    steps = []
                    for step in msg_obj.get("step_history", []):
                        for sd in step.get("step_details", []):
                            steps.append(sd)

                    # 4. Asynchronously record new preference/fact in Mem0
                    record_user_memory(user_id=user_id, text=f"User said: {req.message}. Assistant replied: {reply_text}")

                    return {
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "reply": reply_text,
                        "steps": steps,
                        "agent_used": agent_spec["title"],
                        "recalled_memories": recalled_memories,
                        "dynamic_token": dyn_token,
                        "user": user,
                    }
            

    raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Agent run timed out")


@app.get("/health")
def health():
    return {"status": "ok", "app": "Bean & Brew Enterprise BFF"}
