"""RBAC verification against Snowflake: every role x resource must match docs/rbac.md.
Run: venv/bin/python tests/test_snowflake_rbac.py
"""
import os
import pathlib
import sys

import snowflake.connector

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


ENV = load_env()


def connect(role):
    return snowflake.connector.connect(
        account=ENV["SNOWFLAKE_ACCOUNT"], user=f"BB_{role}_SVC",
        password=ENV[f"SNOWFLAKE_BB_{role}_PASSWORD"], warehouse="BB_WH",
        database="BEAN_BREW", schema="CORE")


def q(role, sql, store=None, region=None):
    c = connect(role)
    cur = c.cursor()
    try:
        if store:
            cur.execute(f"SET BB_STORE_ID='{store}'")
        if region:
            cur.execute(f"SET BB_REGION='{region}'")
        cur.execute(sql)
        return cur.fetchall()
    finally:
        c.close()


def denied(role, sql, **kw):
    try:
        q(role, sql, **kw)
        return False
    except snowflake.connector.errors.ProgrammingError:
        return True


results = []


def check(name, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name)


# Barista: own-store inventory only, no sales, no employees
rows = q("BARISTA", "select distinct store_id from inventory", store="S01")
check("barista sees only own store inventory", rows == [("S01",)])
check("barista denied sales", denied("BARISTA", "select count(*) from sales", store="S01"))
check("barista denied employees", denied("BARISTA", "select count(*) from employees", store="S01"))

# Manager: own-store sales, employees without salary, inventory update on own store only
rows = q("MANAGER", "select distinct store_id from sales", store="S01")
check("manager sees only own store sales", rows == [("S01",)])
rows = q("MANAGER", "select salary, email, phone from employees limit 3", store="S01")
check("manager: salary masked", all(r[0] is None for r in rows))
check("manager: email/phone masked", all(r[1].startswith("*****") and r[2].startswith("***") for r in rows))
check("manager can update own-store inventory",
      q("MANAGER", "update inventory set on_hand=on_hand where sku='SKU001'", store="S01")[0][0] == 1)
check("manager cannot update other-store inventory",
      q("MANAGER", "update inventory set on_hand=on_hand where store_id='S05'", store="S01")[0][0] == 0)

# Regional: region-scoped, no employees
rows = q("REGIONAL", "select distinct region from sales", region="NORTH")
check("regional sees only own region", rows == [("NORTH",)])
check("regional denied employees", denied("REGIONAL", "select count(*) from employees", region="NORTH"))

# Finance: aggregates only
check("finance denied raw sales", denied("FINANCE", "select count(*) from sales"))
check("finance denied raw employees", denied("FINANCE", "select count(*) from employees"))
check("finance can read sales_daily", q("FINANCE", "select count(*) from sales_daily")[0][0] > 0)
check("finance can read salary_summary", q("FINANCE", "select count(*) from salary_summary")[0][0] > 0)

# HR: everything in employees, unmasked
rows = q("HR", "select salary, email from employees limit 3")
check("hr sees salary and email", all(r[0] is not None and "*" not in r[1] for r in rows))
check("hr denied sales", denied("HR", "select count(*) from sales"))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
