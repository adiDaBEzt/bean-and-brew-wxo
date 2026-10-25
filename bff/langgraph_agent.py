"""Bean & Brew Enterprise LangGraph Agent.

Implements the official IBM Watsonx Orchestrate custom agent pattern using LangGraph:
- Spec: spec_version: v1, framework: langgraph
- Entrypoint: create_graph()
- State: BeanBrewAgentState with cross-turn checkpointer (SqliteSaver)
- Governance: Zero Trust RBAC Gate, Structured EAV Memory, Multi-Hop Graph RAG
- Data Plane: Snowflake RSA 2048 Key-Pair Authentication
"""
import asyncio
import json
import operator
import os
import pathlib
import sqlite3
import time
from typing import Annotated, Any, Dict, List, Optional, TypedDict

import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from bff.graph_rag import format_graph_narrative, query_subgraph
from bff.memory_manager import (
    extract_heuristic_triples,
    search_user_memories,
    upsert_semantic_memory,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY_PATH = ROOT / "snowflake" / "keys" / "rsa_key.p8"
CHECKPOINT_DB_PATH = ROOT / "data" / "langgraph_checkpoints.db"


def _load_rsa_private_key_der() -> Optional[bytes]:
    """Load PKCS#8 RSA 2048 private key for Snowflake key-pair auth."""
    if not KEY_PATH.exists():
        return None
    with open(KEY_PATH, "rb") as f:
        key_bytes = f.read()
    try:
        p_key = serialization.load_pem_private_key(
            key_bytes,
            password=None,
            backend=default_backend(),
        )
        return p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    except Exception:
        return None


ROLE_TO_SVC_USER = {
    "barista": "BB_BARISTA_SVC",
    "store_manager": "BB_MANAGER_SVC",
    "regional_manager": "BB_REGIONAL_SVC",
    "finance_analyst": "BB_FINANCE_SVC",
    "hr_admin": "BB_HR_SVC",
}


def _execute_snowflake_query(
    role: str,
    store_id: str,
    region: str,
    sql: str,
    params: Optional[tuple] = None,
) -> List[Dict[str, Any]]:
    """Execute query via Snowflake using role-specific service user & RSA key."""
    svc_user = ROLE_TO_SVC_USER.get(role, "BB_BARISTA_SVC")
    der_key = _load_rsa_private_key_der()
    if not der_key:
        raise RuntimeError("Snowflake RSA private key not found at snowflake/keys/rsa_key.p8")

    account = os.getenv("SNOWFLAKE_ACCOUNT", "aazghcn-xm19614")
    conn = snowflake.connector.connect(
        account=account,
        user=svc_user,
        warehouse="BB_WH",
        database="BEAN_BREW",
        schema="CORE",
        private_key=der_key,
        session_parameters={"QUERY_TAG": f"langgraph-agent:{role}"},
    )
    try:
        cur = conn.cursor()
        cur.execute("SET BB_STORE_ID = %s", (store_id or "",))
        cur.execute("SET BB_REGION = %s", (region or "",))
        cur.execute(sql, params or ())
        cols = [d[0].lower() for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchall()] if cur.description else []
        return rows
    finally:
        conn.close()


# ============================================================================
# LangGraph Agent State Definition
# ============================================================================

class BeanBrewAgentState(TypedDict):
    """LangGraph State passed across nodes and persisted by SqliteSaver."""
    messages: Annotated[List[Dict[str, Any]], operator.add]
    user_id: str
    role: str
    store_id: str
    region: str
    token: str
    snowflake_user: str
    snowflake_role: str
    # Memory & Graph Augmented Context
    recalled_memories: List[str]
    graph_context: str
    # Intent & RBAC Evaluation
    intent: Optional[str]
    rbac_allowed: bool
    rbac_reason: Optional[str]
    # Execution & Trace History
    tool_calls: List[Dict[str, Any]]
    steps: List[Dict[str, Any]]
    final_reply: Optional[str]
    agent_used: str


# ============================================================================
# LangGraph Agent Nodes
# ============================================================================

def node_memory_recall(state: BeanBrewAgentState) -> Dict[str, Any]:
    """Node 1: Extract heuristics and retrieve Structured Semantic EAV memories."""
    user_id = state.get("user_id", "maya")
    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "")
            break

    # Instant heuristic upsert for declared preferences
    triples = extract_heuristic_triples(last_user_msg)
    for t in triples:
        upsert_semantic_memory(
            user_id=user_id,
            category=t["category"],
            entity=t["entity"],
            attribute=t["attribute"],
            value=t["value"],
            confidence=0.95,
        )

    # Search user memories
    recalled = search_user_memories(user_id=user_id, query=last_user_msg, limit=5)
    step_info = {
        "node": "node_memory_recall",
        "timestamp": time.strftime("%H:%M:%S"),
        "status": "completed",
        "recalled_count": len(recalled),
        "facts": recalled[:3],
    }
    return {
        "recalled_memories": recalled,
        "steps": [step_info],
    }


def node_graph_rag(state: BeanBrewAgentState) -> Dict[str, Any]:
    """Node 2: Multi-Hop Knowledge Graph Traversal for supply chain, recipes & allergens."""
    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "")
            break

    keywords = [
        "supplier", "recipe", "drink", "ingredient", "oat milk",
        "allergen", "gluten", "equipment", "region", "roast", "sku", "oatly",
    ]
    graph_narrative = ""
    nodes_count = 0
    edges_count = 0

    if any(k in last_user_msg.lower() for k in keywords):
        try:
            subg = query_subgraph(entity_query=last_user_msg, depth=2)
            nodes_count = subg.get("total_nodes", 0)
            edges_count = subg.get("total_edges", 0)
            graph_narrative = format_graph_narrative(subg)
        except Exception:
            pass

    step_info = {
        "node": "node_graph_rag",
        "timestamp": time.strftime("%H:%M:%S"),
        "status": "completed",
        "nodes_found": nodes_count,
        "edges_found": edges_count,
    }
    return {
        "graph_context": graph_narrative,
        "steps": [step_info],
    }


def node_zero_trust_rbac_gate(state: BeanBrewAgentState) -> Dict[str, Any]:
    """Node 3: Zero Trust RBAC Gatekeeper inspecting caller role against intent."""
    role = state.get("role", "barista")
    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "").lower()
            break

    # Determine intent
    intent = "general_query"
    if any(w in last_user_msg for w in ["salary", "salaries", "compensation", "payroll", "budget breakdown"]):
        intent = "salary_query"
    elif any(w in last_user_msg for w in ["roster", "employees", "team", "staff", "who works"]):
        intent = "team_roster"
    elif any(w in last_user_msg for w in ["inventory", "stock", "on hand", "low stock"]):
        intent = "inventory_query"
    elif any(w in last_user_msg for w in ["sales", "revenue", "daily sales", "revenue for"]):
        intent = "sales_query"
    elif any(w in last_user_msg for w in ["restock", "order units", "add units"]):
        intent = "restock_inventory"
    elif state.get("graph_context"):
        intent = "graph_knowledge_query"

    # Evaluate RBAC rules
    rbac_allowed = True
    reason = None

    if intent == "salary_query":
        if role not in ["finance_analyst"]:
            rbac_allowed = False
            reason = (
                f"⛔ **Zero Trust RBAC Block**: Role `{role}` is strictly unauthorized to query employee "
                "salary or payroll data. Only `finance_analyst` may view company salary statistics (aggregated only)."
            )
    elif intent == "team_roster":
        if role not in ["store_manager", "hr_admin"]:
            rbac_allowed = False
            reason = (
                f"⛔ **Zero Trust RBAC Block**: Role `{role}` cannot view employee rosters. "
                "Only `store_manager` (for own store with salaries masked) and `hr_admin` (full roster) have access."
            )
    elif intent == "sales_query":
        if role not in ["store_manager", "regional_manager", "finance_analyst"]:
            rbac_allowed = False
            reason = (
                f"⛔ **Zero Trust RBAC Block**: Role `{role}` does not have sales analytics access. "
                "Requires `store_manager`, `regional_manager`, or `finance_analyst`."
            )
    elif intent == "restock_inventory":
        if role not in ["store_manager"]:
            rbac_allowed = False
            reason = (
                f"⛔ **Zero Trust RBAC Block**: Role `{role}` cannot perform write restock transactions. "
                "Inventory restocks can only be executed by `store_manager`."
            )

    step_info = {
        "node": "node_zero_trust_rbac_gate",
        "timestamp": time.strftime("%H:%M:%S"),
        "status": "allowed" if rbac_allowed else "denied",
        "intent": intent,
        "caller_role": role,
    }
    return {
        "intent": intent,
        "rbac_allowed": rbac_allowed,
        "rbac_reason": reason,
        "steps": [step_info],
    }


def should_execute_tools(state: BeanBrewAgentState) -> str:
    """Conditional Edge: Route to tool execution or directly synthesize denial."""
    if not state.get("rbac_allowed", True):
        return "node_synthesize"
    return "node_execute_tools"


def node_execute_tools(state: BeanBrewAgentState) -> Dict[str, Any]:
    """Node 4: Execute authorized enterprise Snowflake queries or actions."""
    intent = state.get("intent", "general_query")
    role = state.get("role", "barista")
    store_id = state.get("store_id", "S01")
    region = state.get("region", "NORTH")

    tool_call_record = {}
    step_info = {
        "node": "node_execute_tools",
        "timestamp": time.strftime("%H:%M:%S"),
        "status": "completed",
        "tool_executed": intent,
    }

    try:
        if intent == "inventory_query":
            sql = "SELECT store_id, sku, item, on_hand, reorder_level FROM INVENTORY WHERE on_hand <= reorder_level ORDER BY on_hand LIMIT 10"
            rows = _execute_snowflake_query(role, store_id, region, sql)
            tool_call_record = {
                "tool": "bb_get_inventory",
                "auth_user": ROLE_TO_SVC_USER.get(role),
                "auth_mode": "RSA 2048 PKCS#8 Key-Pair",
                "rows_returned": len(rows),
                "data": rows,
            }
        elif intent == "sales_query":
            if role == "finance_analyst":
                sql = "SELECT product AS grp, SUM(units) AS units, SUM(revenue) AS revenue FROM SALES_DAILY GROUP BY 1 ORDER BY 3 DESC LIMIT 5"
            else:
                sql = "SELECT product AS grp, SUM(qty) AS units, SUM(amount) AS revenue FROM SALES GROUP BY 1 ORDER BY 3 DESC LIMIT 5"
            rows = _execute_snowflake_query(role, store_id, region, sql)
            tool_call_record = {
                "tool": "bb_get_sales_summary",
                "auth_user": ROLE_TO_SVC_USER.get(role),
                "auth_mode": "RSA 2048 PKCS#8 Key-Pair",
                "rows_returned": len(rows),
                "data": rows,
            }
        elif intent == "team_roster":
            sql = "SELECT emp_id, name, email, store_id, role, salary FROM EMPLOYEES ORDER BY store_id, name LIMIT 10"
            rows = _execute_snowflake_query(role, store_id, region, sql)
            # Mask salary if store manager
            if role == "store_manager":
                for r in rows:
                    r["salary"] = "REDACTED (Store Manager Mask)"
            tool_call_record = {
                "tool": "bb_get_team_roster",
                "auth_user": ROLE_TO_SVC_USER.get(role),
                "auth_mode": "RSA 2048 PKCS#8 Key-Pair",
                "rows_returned": len(rows),
                "data": rows,
            }
        elif intent == "salary_query" and role == "finance_analyst":
            sql = "SELECT region, role, SUM(headcount) AS headcount, ROUND(AVG(total_salary)/AVG(headcount), 0) AS avg_salary, SUM(total_salary) AS total_salary FROM SALARY_SUMMARY GROUP BY 1, 2"
            rows = _execute_snowflake_query(role, store_id, region, sql)
            tool_call_record = {
                "tool": "bb_get_salary_summary",
                "auth_user": ROLE_TO_SVC_USER.get(role),
                "auth_mode": "RSA 2048 PKCS#8 Key-Pair",
                "rows_returned": len(rows),
                "data": rows,
            }
    except Exception as e:
        tool_call_record = {
            "tool": intent,
            "error": str(e),
        }

    return {
        "tool_calls": [tool_call_record] if tool_call_record else [],
        "steps": [step_info],
    }


def node_synthesize(state: BeanBrewAgentState) -> Dict[str, Any]:
    """Node 4: Synthesize response with Collaborator agent attribution and clean tables."""
    # If blocked by RBAC
    if not state.get("rbac_allowed", True):
        reply = state.get("rbac_reason", "Access denied by Zero Trust policy.")
        return {
            "final_reply": reply,
            "agent_used": "Master Operations Agent (RBAC Gatekeeper)",
            "messages": [{"role": "assistant", "content": reply}],
            "steps": [{"node": "node_synthesize", "timestamp": time.strftime("%H:%M:%S"), "status": "rbac_denied"}],
        }

    intent = state.get("intent", "general_query")
    role = state.get("role", "barista")
    store_id = state.get("store_id", "S01")
    recalled = state.get("recalled_memories", [])
    tool_calls = state.get("tool_calls", [])

    lines = []
    agent_label = "Master Operations Agent (Unified Orchestrator)"

    # Recalled preference acknowledgment
    if recalled:
        lines.append(f"*(Noted personal preference: {recalled[0]})*\n")

    # Tool outcomes
    if tool_calls and "data" in tool_calls[0]:
        data = tool_calls[0]["data"]
        tool_name = tool_calls[0]["tool"]

        if tool_name == "bb_get_inventory":
            agent_label = "Master Operations Agent ➔ Executed bb_get_inventory (Snowflake Core)"
            lines.append(f"📦 **Store {store_id} Inventory Levels (Snowflake Core):**\n")
            lines.append("| SKU | Item | On Hand | Reorder Level | Status |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for r in data:
                status = "⚠️ LOW STOCK" if r.get("on_hand", 0) <= r.get("reorder_level", 0) else "✅ Normal"
                lines.append(f"| `{r.get('sku')}` | {r.get('item')} | **{r.get('on_hand')}** | {r.get('reorder_level')} | {status} |")
            lines.append("\n*Authenticated via Snowflake RSA 2048 key-pair credentials.*")

        elif tool_name == "bb_get_sales_summary":
            agent_label = "Master Operations Agent ➔ Executed bb_get_sales_summary (Snowflake Core)"
            lines.append("📊 **Sales Revenue Performance (Snowflake Core):**\n")
            lines.append("| Product / Dimension | Units Sold | Total Revenue |")
            lines.append("| :--- | :--- | :--- |")
            for r in data:
                rev = f"${float(r.get('revenue', 0)):,.2f}"
                lines.append(f"| **{r.get('grp')}** | {r.get('units')} units | {rev} |")

        elif tool_name == "bb_get_team_roster":
            agent_label = "Master Operations Agent ➔ Delegated to bb_hr_agent (HR Collaborator)"
            lines.append(f"👥 **Team Roster (Store {store_id}) — via bb_hr_agent:**\n")
            lines.append("| Employee | Role | Email | Salary Access |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for r in data:
                lines.append(f"| **{r.get('name')}** | `{r.get('role')}` | {r.get('email')} | `{r.get('salary', 'N/A')}` |")

        elif tool_name == "bb_get_salary_summary":
            agent_label = "Master Operations Agent ➔ Delegated to bb_finance_agent (Finance Collaborator)"
            lines.append("💼 **Salary Statistics (Finance Aggregates) — via bb_finance_agent:**\n")
            lines.append("| Region | Role | Headcount | Avg Salary | Total Budget |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for r in data:
                lines.append(f"| {r.get('region')} | `{r.get('role')}` | {r.get('headcount')} | ${float(r.get('avg_salary', 0)):,.2f} | ${float(r.get('total_salary', 0)):,.2f} |")

    else:
        lines.append(f"☕ Hello! I am the **Bean & Brew Master Operations Agent**.")
        lines.append(f"You are authenticated as **{role}** (Store **{store_id}**).")
        lines.append("I can assist you with store operations, team rosters (via `bb_hr_agent`), financial statistics (via `bb_finance_agent`), and Snowflake inventory.")

    reply_content = "\n".join(lines)
    return {
        "final_reply": reply_content,
        "agent_used": agent_label,
        "messages": [{"role": "assistant", "content": reply_content}],
        "steps": [{"node": "node_synthesize", "timestamp": time.strftime("%H:%M:%S"), "status": "completed"}],
    }


# ============================================================================
# Graph Construction & WXO SDK Entrypoint
# ============================================================================

_SAVER_CONN: Optional[sqlite3.Connection] = None
_CHECKPOINTER: Optional[SqliteSaver] = None


def get_sqlite_checkpointer() -> SqliteSaver:
    """Initialize or reuse singleton SQLite checkpointer for LangGraph cross-turn state."""
    global _SAVER_CONN, _CHECKPOINTER
    if _CHECKPOINTER is None:
        CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SAVER_CONN = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
        _SAVER_CONN.execute("PRAGMA journal_mode=WAL;")
        _SAVER_CONN.execute("PRAGMA synchronous=NORMAL;")
        _CHECKPOINTER = SqliteSaver(_SAVER_CONN)
    return _CHECKPOINTER


def create_bean_brew_graph(checkpointer: Optional[SqliteSaver] = None):
    """Build and compile the Bean & Brew StateGraph without cluttered graph RAG."""
    chk = checkpointer or get_sqlite_checkpointer()
    builder = StateGraph(BeanBrewAgentState)

    # Add Nodes
    builder.add_node("node_memory_recall", node_memory_recall)
    builder.add_node("node_zero_trust_rbac_gate", node_zero_trust_rbac_gate)
    builder.add_node("node_execute_tools", node_execute_tools)
    builder.add_node("node_synthesize", node_synthesize)

    # Add Edges
    builder.add_edge(START, "node_memory_recall")
    builder.add_edge("node_memory_recall", "node_zero_trust_rbac_gate")

    # Conditional edge based on RBAC gate decision
    builder.add_conditional_edges(
        "node_zero_trust_rbac_gate",
        should_execute_tools,
        {
            "node_execute_tools": "node_execute_tools",
            "node_synthesize": "node_synthesize",
        },
    )

    builder.add_edge("node_execute_tools", "node_synthesize")
    builder.add_edge("node_synthesize", END)

    return builder.compile(checkpointer=chk)


# Top-level entrypoint for Watsonx Orchestrate code bundle specification
create_graph = create_bean_brew_graph
compiled_agent = create_bean_brew_graph()
