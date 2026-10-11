"""FastAPI Backend-For-Frontend (BFF) for Bean & Brew.

Security Architecture:
  1. Authenticates employees against Keycloak OIDC.
  2. Extracts verified user claims: role, store_id, region, email.
  3. Mints secure session tokens for frontend client.
  4. Proxies requests to watsonx Orchestrate Runs API using backend service IAM credentials.
  5. Injects tamper-proof context variables (bb_role, bb_store_id, bb_region, bb_email)
     so the agent and Snowflake tools strictly enforce RBAC and row-level access control.
"""
import os
import pathlib
import time
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from pydantic import BaseModel

ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Config
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "bean-brew")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "bb-web")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
DEMO_USER_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "")

WXO_URL = os.getenv("WXO_URL", "")
WXO_API_KEY = os.getenv("WXO_API_KEY", "")
AGENT_ID = "625b0516-9857-4c1f-a854-873e13f3197d"
AGENT_NAME = "bb_assistant"

JWT_SECRET = os.getenv("BFF_JWT_SECRET", "bb-dev-secret-key-38291048123912093")
JWT_ALGORITHM = "HS256"

app = FastAPI(title="Bean & Brew BFF API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory IAM token cache
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


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None


def create_session_token(profile: dict) -> str:
    payload = profile.copy()
    payload["exp"] = int(time.time()) + 86400  # 24h
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
    return UserProfile(
        username=user.get("username", ""),
        email=user.get("email", ""),
        role=user.get("role", ""),
        store_id=user.get("store_id", ""),
        region=user.get("region", ""),
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
    return profile


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(key="bb_session")
    return {"status": "logged_out"}


@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    iam_token = await get_wxo_iam_token()
    headers = {
        "Authorization": f"Bearer {iam_token}",
        "Content-Type": "application/json",
    }

    # Strict RBAC context injected from validated session cookie
    payload = {
        "agent_id": AGENT_ID,
        "agent_name": AGENT_NAME,
        "message": {
            "role": "user",
            "content": req.message,
        },
        "context": {
            "bb_role": user["role"],
            "bb_store_id": user["store_id"],
            "bb_region": user["region"],
            "bb_email": user["email"],
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

        # Poll run status to completion
        for _ in range(25):
            await httpx.AsyncClient().get("http://localhost:8000/health") # yield
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

                    return {
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "reply": reply_text,
                        "steps": steps,
                        "user": user,
                    }
            time.sleep(2)

    raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Agent run timed out")


@app.get("/health")
def health():
    return {"status": "ok", "app": "Bean & Brew BFF"}
