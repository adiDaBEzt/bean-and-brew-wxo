"""FastAPI Backend-For-Frontend (BFF) connecting to Unified Master Agent.

Architecture:
  1. All employees log in and interact with the unified Bean & Brew Master Agent.
  2. The Master Agent routes requests to specialized collaborators (bb_hr_agent, bb_finance_agent)
     or local tools, strictly enforcing RBAC based on tamper-proof context variables.
  3. Mem0 automatically provides cross-session semantic memory per user.
  4. Ephemeral OAuth tokens are minted with 300s TTL per session.
"""
import os
import pathlib
import time
import asyncio
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from pydantic import BaseModel

from bff.memory_manager import (
    get_embedder,
    get_user_semantic_facts,
    init_db,
    record_user_memory,
    search_user_memories,
)
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

MASTER_AGENT_ID = "c26a5051-2017-4987-ab41-fb26c8f4c439"
MASTER_AGENT_NAME = "bb_master_agent"

JWT_SECRET = os.getenv("BFF_JWT_SECRET", "bb-dev-secret-key-38291048123912093")
JWT_ALGORITHM = "HS256"

app = FastAPI(title="Bean & Brew Enterprise BFF API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(asyncio.to_thread(get_embedder))

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
    accessible_agents: List[dict] = []
    dynamic_token: dict


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None


MASTER_AGENTS_LIST = [
    {
        "name": MASTER_AGENT_NAME,
        "title": "Master Operations Agent (Autonomous Zero Trust Router)",
        "id": MASTER_AGENT_ID,
    }
]


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


@app.get("/api/auth/me", response_model=UserProfile)
def get_me(user: dict = Depends(get_current_user)):
    role = user.get("role", "")
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
        accessible_agents=MASTER_AGENTS_LIST,
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
    dyn_token = token_broker.mint_token(
        username=profile["username"],
        role=primary_role,
        store_id=profile["store_id"],
        region=profile["region"],
    )
    return {**profile, "accessible_agents": MASTER_AGENTS_LIST, "dynamic_token": dyn_token}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(key="bb_session")
    return {"status": "logged_out"}


@app.get("/api/memory")
def get_memories(user: dict = Depends(get_current_user)):
    user_id = user["username"]
    memories = search_user_memories(user_id=user_id, query="preferences and facts", limit=20)
    facts = get_user_semantic_facts(user_id=user_id)
    return {"user_id": user_id, "memories": memories, "facts": facts}


@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    # 1. Retrieve relevant long-term memories from Structured Semantic Memory
    user_id = user["username"]
    recalled_memories = []
    try:
        recalled_memories = await asyncio.wait_for(
            asyncio.to_thread(search_user_memories, user_id=user_id, query=req.message, limit=5),
            timeout=3.0,
        )
    except Exception:
        recalled_memories = []

    memory_context_str = ""
    if recalled_memories:
        memory_context_str = "\n<user_preferences>\n" + "\n".join(f"- {m}" for m in recalled_memories) + "\n</user_preferences>"

    # 2. Ephemeral Snowflake Token
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

    # Strict Context Variables passed to Master Agent
    payload = {
        "agent_id": MASTER_AGENT_ID,
        "agent_name": MASTER_AGENT_NAME,
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

                    # 3. Asynchronously persist in Mem0 in background
                    asyncio.create_task(
                        asyncio.to_thread(
                            record_user_memory,
                            user_id=user_id,
                            text=f"User said: {req.message}. Assistant replied: {reply_text}",
                        )
                    )

                    return {
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "reply": reply_text,
                        "steps": steps,
                        "agent_used": "Bean & Brew Master Operations Agent",
                        "recalled_memories": recalled_memories,
                        "dynamic_token": dyn_token,
                        "user": user,
                    }

    raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Agent run timed out")


@app.get("/health")
def health():
    return {"status": "ok", "app": "Bean & Brew Master BFF"}
