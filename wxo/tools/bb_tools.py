"""Bean & Brew Snowflake tools for watsonx Orchestrate.

Security model (defence in depth, see docs/identity-flow.md):
  1. `bb_role`, `bb_store_id`, `bb_region` are WXO *context variables*. They come from the signed
     embed JWT / Runs API `context`, are filled in by the runtime, and the LLM cannot change them.
  2. Every tool checks the caller's role against its own allow-list (tool-level RBAC).
  3. The tool then connects to Snowflake as the *least-privileged Snowflake role* for that caller,
     using a per-role WXO connection. A tool is only bound to the connections of roles that are
     allowed to use it, so e.g. the sales tool can never obtain HR credentials.
  4. Snowflake row access / masking policies are the final enforcement layer.
"""
from contextlib import contextmanager

import snowflake.connector
from ibm_watsonx_orchestrate.agent_builder.connections import ConnectionType
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.run import connections

# app roles (Keycloak realm roles) -> Snowflake role suffix / WXO connection
ROLE_TO_SF = {
    "barista": "barista",
    "store_manager": "manager",
    "regional_manager": "regional",
    "finance_analyst": "finance",
    "hr_admin": "hr",
}


def _conn_id(sf_role: str) -> str:
    return f"bb_sf_{sf_role}"


def _creds(sf_roles):
    return [{"app_id": _conn_id(r), "type": ConnectionType.KEY_VALUE} for r in sf_roles]


class AccessDenied(Exception):
    pass


@contextmanager
def _session(bb_role: str, allowed: set, bb_store_id: str, bb_region: str):
    """Tool-level RBAC check, then a Snowflake session as the caller's own Snowflake role."""
    role = (bb_role or "").strip()
    if role not in allowed:
        raise AccessDenied(
            f"Access denied: role '{role or 'unknown'}' is not allowed to use this tool. "
            f"Allowed roles: {', '.join(sorted(allowed))}."
        )
    c = connections.key_value(_conn_id(ROLE_TO_SF[role]))
    conn = snowflake.connector.connect(
        account=c["account"], user=c["user"], password=c["password"],
        warehouse="BB_WH", database="BEAN_BREW", schema="CORE",
        session_parameters={"QUERY_TAG": f"wxo-bean-brew:{role}"},
    )
    try:
        cur = conn.cursor()
        # Scope variables consumed by the Snowflake row access policy. Bound values, never concatenated.
        cur.execute("SET BB_STORE_ID = %s", (bb_store_id or "",))
        cur.execute("SET BB_REGION = %s", (bb_region or "",))
        yield cur
    finally:
        conn.close()


def _rows(cur, sql, params=None):
    cur.execute(sql, params or ())
    cols = [d[0].lower() for d in cur.description]
    return [dict(zip(cols, [str(v) if not isinstance(v, (int, float, type(None))) else v for v in r])) for r in cur.fetchall()]


@tool(name="bb_whoami", description="Explain who the current user is, based on the verified identity context, and which Bean & Brew tools and data that role may use.")
def bb_whoami(bb_role: str = "", bb_store_id: str = "", bb_region: str = "", bb_email: str = "") -> dict:
    """
    Args:
        bb_role: Verified role of the user (filled automatically from context).
        bb_store_id: Verified store of the user (filled automatically from context).
        bb_region: Verified region of the user (filled automatically from context).
        bb_email: Verified email of the user (filled automatically from context).
    """
    perms = {
        "barista": ["bb_get_inventory (own store, read-only)"],
        "store_manager": ["bb_get_sales_summary (own store)", "bb_get_inventory (own store)",
                          "bb_restock_inventory (own store)", "bb_get_team_roster (own team, salary hidden)"],
        "regional_manager": ["bb_get_sales_summary (own region)", "bb_get_inventory (own region)"],
        "finance_analyst": ["bb_get_sales_summary (company-wide aggregates)", "bb_get_salary_summary (aggregates only)"],
        "hr_admin": ["bb_get_team_roster (all employees, full details)"],
    }
    return {"email": bb_email, "role": bb_role, "store_id": bb_store_id, "region": bb_region,
            "permitted_tools": perms.get(bb_role, [])}


@tool(name="bb_get_sales_summary",
      description="Summarise Bean & Brew sales (units and revenue) over the last N days, grouped by product, store, region or day. Results are automatically limited to what the user's role may see.",
      expected_credentials=_creds(["manager", "regional", "finance"]))
def bb_get_sales_summary(group_by: str = "product", days: int = 7,
                         bb_role: str = "", bb_store_id: str = "", bb_region: str = "") -> dict:
    """
    Args:
        group_by: One of product, store, region, day.
        days: Look-back window in days (1-90).
        bb_role: Verified role (filled automatically from context).
        bb_store_id: Verified store (filled automatically from context).
        bb_region: Verified region (filled automatically from context).
    """
    dims = {"product": "product", "store": "store_id", "region": "region", "day": "day"}
    if group_by not in dims:
        return {"error": f"group_by must be one of {sorted(dims)}"}
    days = max(1, min(int(days), 90))
    try:
        with _session(bb_role, {"store_manager", "regional_manager", "finance_analyst"}, bb_store_id, bb_region) as cur:
            if bb_role == "finance_analyst":  # finance only has the aggregate view
                col = dims[group_by]
                sql = (f"SELECT {col} AS grp, SUM(units) AS units, SUM(revenue) AS revenue FROM SALES_DAILY "
                       f"WHERE day >= DATEADD(day, -%s, (SELECT MAX(day) FROM SALES_DAILY)) GROUP BY 1 ORDER BY 3 DESC LIMIT 20")
            else:
                col = "DATE(ts)" if group_by == "day" else dims[group_by]
                sql = (f"SELECT {col} AS grp, SUM(qty) AS units, SUM(amount) AS revenue FROM SALES "
                       f"WHERE ts >= DATEADD(day, -%s, (SELECT MAX(ts) FROM SALES)) GROUP BY 1 ORDER BY 3 DESC LIMIT 20")
            return {"group_by": group_by, "days": days, "rows": _rows(cur, sql, (days,))}
    except AccessDenied as e:
        return {"error": str(e)}


@tool(name="bb_get_inventory",
      description="Show inventory levels for the user's store or region, optionally only items below their reorder level.",
      expected_credentials=_creds(["barista", "manager", "regional"]))
def bb_get_inventory(low_stock_only: bool = True,
                     bb_role: str = "", bb_store_id: str = "", bb_region: str = "") -> dict:
    """
    Args:
        low_stock_only: If true, only items at or below the reorder level.
        bb_role: Verified role (filled automatically from context).
        bb_store_id: Verified store (filled automatically from context).
        bb_region: Verified region (filled automatically from context).
    """
    try:
        with _session(bb_role, {"barista", "store_manager", "regional_manager"}, bb_store_id, bb_region) as cur:
            where = "WHERE on_hand <= reorder_level" if low_stock_only else ""
            sql = (f"SELECT store_id, sku, item, on_hand, reorder_level FROM INVENTORY {where} "
                   "ORDER BY store_id, on_hand - reorder_level LIMIT 40")
            return {"rows": _rows(cur, sql)}
    except AccessDenied as e:
        return {"error": str(e)}


@tool(name="bb_restock_inventory",
      description="Record a restock (add units) for one inventory SKU in the manager's own store. Store managers only.",
      expected_credentials=_creds(["manager"]))
def bb_restock_inventory(sku: str, quantity: int,
                         bb_role: str = "", bb_store_id: str = "", bb_region: str = "") -> dict:
    """
    Args:
        sku: Inventory SKU code such as SKU003.
        quantity: Units to add (1-500).
        bb_role: Verified role (filled automatically from context).
        bb_store_id: Verified store (filled automatically from context).
        bb_region: Verified region (filled automatically from context).
    """
    quantity = int(quantity)
    if not 1 <= quantity <= 500:
        return {"error": "quantity must be between 1 and 500"}
    try:
        with _session(bb_role, {"store_manager"}, bb_store_id, bb_region) as cur:
            # The row access policy confines this UPDATE to the manager's own store.
            cur.execute("UPDATE INVENTORY SET on_hand = on_hand + %s, updated_at = CURRENT_TIMESTAMP() "
                        "WHERE sku = %s AND store_id = %s", (quantity, sku.upper(), bb_store_id))
            updated = cur.rowcount
            return {"updated_rows": updated, "sku": sku.upper(), "added": quantity, "store_id": bb_store_id}
    except AccessDenied as e:
        return {"error": str(e)}


@tool(name="bb_get_team_roster",
      description="List employees. Store managers see their own store team with salary and contact details hidden; HR admins see everyone in full.",
      expected_credentials=_creds(["manager", "hr"]))
def bb_get_team_roster(bb_role: str = "", bb_store_id: str = "", bb_region: str = "") -> dict:
    """
    Args:
        bb_role: Verified role (filled automatically from context).
        bb_store_id: Verified store (filled automatically from context).
        bb_region: Verified region (filled automatically from context).
    """
    try:
        with _session(bb_role, {"store_manager", "hr_admin"}, bb_store_id, bb_region) as cur:
            sql = ("SELECT emp_id, name, email, phone, store_id, role, salary FROM EMPLOYEES "
                   "ORDER BY store_id, role, name LIMIT 30")
            return {"rows": _rows(cur, sql)}
    except AccessDenied as e:
        return {"error": str(e)}


@tool(name="bb_get_salary_summary",
      description="Aggregated salary statistics (headcount, average, total) by store and role. Finance analysts only; individual salaries are never exposed.",
      expected_credentials=_creds(["finance"]))
def bb_get_salary_summary(bb_role: str = "", bb_store_id: str = "", bb_region: str = "") -> dict:
    """
    Args:
        bb_role: Verified role (filled automatically from context).
        bb_store_id: Verified store (filled automatically from context).
        bb_region: Verified region (filled automatically from context).
    """
    try:
        with _session(bb_role, {"finance_analyst"}, bb_store_id, bb_region) as cur:
            sql = ("SELECT region, role, SUM(headcount) AS headcount, ROUND(SUM(total_salary) / SUM(headcount), 0) AS avg_salary, "
                   "SUM(total_salary) AS total_salary FROM SALARY_SUMMARY GROUP BY 1, 2 ORDER BY 1, 2")
            return {"rows": _rows(cur, sql)}
    except AccessDenied as e:
        return {"error": str(e)}
