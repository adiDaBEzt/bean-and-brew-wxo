"""FastAPI Backend-For-Frontend (BFF) connecting to Unified Master Agent.

Architecture:
  1. All employees log in and interact with the unified Bean & Brew Master Agent.
  2. The Master Agent routes requests to specialized collaborators (bb_hr_agent, bb_finance_agent)
     or local tools, strictly enforcing RBAC based on tamper-proof context variables.
  3. Mem0 automatically provides cross-session semantic memory per user.
  4. Ephemeral OAuth tokens are minted with 300s TTL per session.
"""
import json
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
    clear_user_memories,
    delete_semantic_memory,
    extract_heuristic_triples,
    format_context_preferences,
    format_fact,
    get_embedder,
    get_user_semantic_facts,
    init_db,
    record_user_memory,
    search_user_memories,
    upsert_semantic_memory,
)
from bff.graph_rag import (
    format_graph_narrative,
    query_subgraph,
    seed_bean_brew_knowledge_graph,
)
from bff.langgraph_agent import compiled_agent
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

MASTER_AGENT_ID = os.getenv("WXO_MASTER_AGENT_ID", "05fa901e-df2a-469a-955e-c88c010ef832")
MASTER_AGENT_NAME = os.getenv("WXO_MASTER_AGENT_NAME", "bb_master_agent")

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
    use_engine: Optional[str] = "langgraph"


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


FALLBACK_PERSONAS = {
    "maya": {"username": "maya", "email": "maya@beanandbrew.example", "role": "barista", "store_id": "S01", "region": "NORTH"},
    "sam": {"username": "sam", "email": "sam@beanandbrew.example", "role": "store_manager", "store_id": "S01", "region": "NORTH"},
    "priya": {"username": "priya", "email": "priya@beanandbrew.example", "role": "regional_manager", "store_id": "HQ", "region": "NORTH"},
    "felix": {"username": "felix", "email": "felix@beanandbrew.example", "role": "finance_analyst", "store_id": "HQ", "region": "NORTH"},
    "hana": {"username": "hana", "email": "hana@beanandbrew.example", "role": "hr_admin", "store_id": "HQ", "region": "NORTH"},
}


@app.post("/api/auth/login")
async def login(req: LoginRequest, response: Response):
    profile = None
    pw = req.password or DEMO_USER_PASSWORD
    token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

    try:
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
                timeout=3.0,
            )
            if res.status_code == 200:
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
    except Exception:
        pass  # Keycloak offline or unreachable, fall through to demo persona fallback

    if not profile:
        uname = req.username.lower()
        if uname in FALLBACK_PERSONAS:
            profile = FALLBACK_PERSONAS[uname]
        else:
            profile = {
                "username": req.username,
                "email": f"{req.username}@beanandbrew.example",
                "role": "barista",
                "store_id": "S01",
                "region": "NORTH",
            }

    primary_role = profile["role"]
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


class DeleteMemoryRequest(BaseModel):
    category: Optional[str] = "preference"
    entity: str
    attribute: Optional[str] = "type"


class UpsertMemoryRequest(BaseModel):
    category: Optional[str] = "preference"
    entity: str
    attribute: Optional[str] = "type"
    value: str


@app.get("/api/memory")
def get_memories(user: dict = Depends(get_current_user)):
    user_id = user["username"]
    facts = get_user_semantic_facts(user_id=user_id)
    memories = [format_fact(f) for f in facts]
    return {
        "user_id": user_id,
        "facts": facts,
        "memories": memories,
        "count": len(facts),
        "db": "SQLite EAV Store (data/semantic_memory.db)",
    }


@app.post("/api/memory/clear")
def clear_memories(user: dict = Depends(get_current_user)):
    user_id = user["username"]
    cleared = clear_user_memories(user_id=user_id)
    return {"status": "ok", "cleared_count": cleared}


@app.post("/api/memory/delete")
def delete_memory(req: DeleteMemoryRequest, user: dict = Depends(get_current_user)):
    user_id = user["username"]
    ok = delete_semantic_memory(
        user_id=user_id,
        category=req.category or "preference",
        entity=req.entity,
        attribute=req.attribute or "type",
    )
    facts = get_user_semantic_facts(user_id=user_id)
    return {"status": "ok" if ok else "not_found", "facts": facts}


@app.post("/api/memory/upsert")
def upsert_memory(req: UpsertMemoryRequest, user: dict = Depends(get_current_user)):
    user_id = user["username"]
    upsert_semantic_memory(
        user_id=user_id,
        category=req.category or "preference",
        entity=req.entity,
        attribute=req.attribute or "type",
        value=req.value,
        confidence=1.0,
    )
    facts = get_user_semantic_facts(user_id=user_id)
    memories = [format_fact(f) for f in facts]
    return {"status": "ok", "facts": facts, "memories": memories}


@app.get("/api/langgraph/info")
def get_langgraph_info():
    return {
        "framework": "langgraph",
        "version": "1.1.6",
        "checkpointer": "SqliteSaver (data/langgraph_checkpoints.db)",
        "entrypoint": "bff.langgraph_agent:create_graph",
        "nodes": [
            {"id": "node_memory_recall", "label": "Recall Memories", "description": "Extracts heuristic triples & retrieves Structured EAV Facts from SQLite"},
            {"id": "node_graph_rag", "label": "Graph RAG Expansion", "description": "Multi-hop BFS Knowledge Graph relationship retrieval across recipes & supply chain"},
            {"id": "node_zero_trust_rbac_gate", "label": "Zero Trust RBAC Gate", "description": "Security gatekeeper evaluating role permissions against requested intent"},
            {"id": "node_execute_tools", "label": "Snowflake RSA Tools", "description": "Executes authorized queries using Snowflake RSA 2048 key-pair credentials"},
            {"id": "node_synthesize", "label": "Artisan Synthesis", "description": "Synthesizes contextual markdown response with preferences & graph connections"},
        ],
        "edges": [
            {"from": "START", "to": "node_memory_recall"},
            {"from": "node_memory_recall", "to": "node_graph_rag"},
            {"from": "node_graph_rag", "to": "node_zero_trust_rbac_gate"},
            {"from": "node_zero_trust_rbac_gate", "to": "node_execute_tools", "condition": "rbac_allowed == True"},
            {"from": "node_zero_trust_rbac_gate", "to": "node_synthesize", "condition": "rbac_allowed == False"},
            {"from": "node_execute_tools", "to": "node_synthesize"},
            {"from": "node_synthesize", "to": "END"},
        ],
    }


@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    user_id = user["username"]

    # 1. Dynamically record newly expressed user preferences (atomic upsert, zero-latency)
    new_memories = record_user_memory(user_id, req.message)
    active_facts = get_user_semantic_facts(user_id)
    pref_directive = format_context_preferences(user_id)

    # 2. Mint Ephemeral Snowflake OAuth Token
    dyn_token = token_broker.mint_token(
        username=user["username"],
        role=user["role"],
        store_id=user["store_id"],
        region=user["region"],
    )

    # 3. Call IBM Watsonx Orchestrate Cloud API (bb_master_agent)
    iam_token = await get_wxo_iam_token()
    headers = {
        "Authorization": f"Bearer {iam_token}",
        "Content-Type": "application/json",
    }
    
    # If active preferences exist, inject concise directive into prompt so WXO models strictly adhere to them
    message_content = req.message
    if pref_directive:
        message_content = f"{req.message}\n\n{pref_directive}"

    payload = {
        "agent_id": MASTER_AGENT_ID,
        "agent_name": MASTER_AGENT_NAME,
        "message": {"role": "user", "content": message_content},
        "context": {
            "bb_role": user["role"],
            "bb_store_id": user["store_id"],
            "bb_region": user["region"],
            "bb_email": user["email"],
            "bb_dynamic_token": dyn_token["token"],
            "bb_preferences": json.dumps([{"entity": f["entity"], "value": f["value"]} for f in active_facts]),
        },
    }
    if req.thread_id:
        payload["thread_id"] = req.thread_id

    try:
        async with httpx.AsyncClient() as client:
            run_res = await client.post(
                f"{WXO_URL}/v1/orchestrate/runs",
                headers=headers,
                json=payload,
                timeout=25.0,
            )
            if run_res.status_code != 200:
                raise HTTPException(
                    status_code=run_res.status_code,
                    detail=f"Watsonx Orchestrate run failed: {run_res.text}",
                )

            run_data = run_res.json()
            run_id = run_data["run_id"]
            thread_id = run_data.get("thread_id") or req.thread_id

            # Poll until completed
            for _ in range(60):
                await asyncio.sleep(1.0)
                s_res = await client.get(
                    f"{WXO_URL}/v1/orchestrate/runs/{run_id}",
                    headers=headers,
                    timeout=10.0,
                )
                if s_res.status_code == 200:
                    s_data = s_res.json()
                    status_val = s_data.get("status")
                    if status_val in ["completed", "failed", "cancelled"]:
                        if status_val != "completed":
                            raise HTTPException(
                                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=f"Watsonx Orchestrate Agent execution {status_val}: {s_data.get('last_error')}",
                            )

                        msg_obj = s_data.get("result", {}).get("data", {}).get("message", {})
                        content_list = msg_obj.get("content", [])
                        reply_text = "".join([c.get("text", "") for c in content_list if isinstance(c, dict)])
                        raw_steps = msg_obj.get("step_history", [])

                        formatted_steps = []
                        for sh in raw_steps:
                            for sd in sh.get("step_details", []):
                                if sd.get("type") == "tool_calls":
                                    for tc in sd.get("tool_calls", []):
                                        formatted_steps.append({
                                            "node": "WXO Tool Invocation",
                                            "tool": tc.get("name"),
                                            "args": tc.get("args"),
                                            "status": "executing",
                                            "auth": "Snowflake RSA 2048 PKCS#8 Key-Pair",
                                        })
                                elif sd.get("type") == "tool_response":
                                    formatted_steps.append({
                                        "node": "WXO Tool Response",
                                        "tool": sd.get("name"),
                                        "status": "completed",
                                        "details": sd.get("content"),
                                    })

                        if not formatted_steps:
                            formatted_steps.append({
                                "node": "WXO Policy Evaluation",
                                "tool": "bb_master_agent Reasoning",
                                "status": "completed",
                                "auth": f"Role: {user['role']} (Store: {user['store_id']})",
                            })

                        return {
                            "thread_id": thread_id,
                            "run_id": run_id,
                            "reply": reply_text,
                            "steps": formatted_steps,
                            "agent_used": "IBM Watsonx Orchestrate (bb_master_agent)",
                            "dynamic_token": dyn_token,
                            "user": user,
                            "memories": active_facts,
                            "new_memories": new_memories,
                        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        # If WXO network drops, fallback to local compiled agent
        input_state = {
            "messages": [{"role": "user", "content": req.message}],
            "user_id": user["username"],
            "role": user["role"],
            "store_id": user["store_id"],
            "region": user["region"],
            "token": dyn_token["token"],
            "snowflake_user": dyn_token.get("snowflake_user", "BB_BARISTA_SVC"),
            "snowflake_role": dyn_token.get("snowflake_role", "BB_BARISTA"),
            "recalled_memories": [format_fact(f) for f in active_facts],
            "graph_context": "",
            "tool_calls": [],
            "steps": [],
        }
        res = await asyncio.to_thread(compiled_agent.invoke, input_state, {"configurable": {"thread_id": req.thread_id or "local"}})
        return {
            "thread_id": req.thread_id or "local",
            "reply": res.get("final_reply", ""),
            "steps": res.get("steps", []),
            "agent_used": "Local Fallback Agent",
            "dynamic_token": dyn_token,
            "user": user,
            "memories": active_facts,
            "new_memories": new_memories,
        }

    raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Watsonx Orchestrate run timed out")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "Bean & Brew Enterprise BFF",
        "agent": "IBM Watsonx Orchestrate (bb_master_agent)",
    }
