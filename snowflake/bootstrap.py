"""Bootstrap the Bean & Brew Snowflake environment (idempotent).

Order: infra -> tables -> seed -> governance -> role users -> verification.
SAFETY: never alters existing users, account parameters or network policies.
Reads secrets from ../.env; writes generated role-user passwords back to ../.env.
"""
import os
import pathlib
import random
import re
import secrets
import sys
from datetime import date, datetime, timedelta

import snowflake.connector

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
SQL_DIR = pathlib.Path(__file__).resolve().parent

ROLES = ["BARISTA", "MANAGER", "REGIONAL", "FINANCE", "HR"]


def load_env():
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def save_env_var(key, value):
    text = ENV_FILE.read_text()
    if re.search(rf"^{key}=", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text += f"{key}={value}\n"
    ENV_FILE.write_text(text)


def run_file(cur, name):
    sql = (SQL_DIR / name).read_text()
    sql = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        try:
            cur.execute(stmt)
        except Exception as e:  # show the failing statement, then stop
            print(f"FAILED in {name}:\n{stmt}\n{e}")
            sys.exit(1)
    print(f"ok  {name}")


# ---------------------------------------------------------------- seed data
REGIONS = {"NORTH": ["Harbor Street", "Pine Hill", "Lakeside", "Old Town"],
           "SOUTH": ["Sunset Plaza", "Palm Court", "Riverwalk", "Market Square"],
           "WEST": ["Cliffside", "Redwood", "Bayview", "Canyon Mall"]}
PRODUCTS = {"Latte": 4.5, "Cappuccino": 4.25, "Americano": 3.25, "Cold Brew": 4.75,
            "Mocha": 5.0, "Flat White": 4.6, "Caramel Frappe": 5.5, "Matcha Latte": 5.25,
            "Espresso": 2.75, "Blueberry Muffin": 3.5, "Butter Croissant": 3.75, "Breakfast Wrap": 6.25}
FIRST = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Emma", "Ravi", "Zoe", "Omar", "Chloe", "Ethan", "Nina",
         "Diego", "Ava", "Kai", "Lena", "Hugo", "Isla", "Jon", "Tara", "Leo", "Mira", "Sean", "Anya"]
LAST = ["Patel", "Garcia", "Nguyen", "Smith", "Kim", "Okafor", "Silva", "Novak", "Haddad", "Brown", "Rossi", "Tan"]


def seed(cur):
    rnd = random.Random(42)
    cur.execute("USE ROLE BB_ADMIN")
    cur.execute("USE WAREHOUSE BB_WH")
    cur.execute("USE SCHEMA BEAN_BREW.CORE")
    for t in ("STORES", "SALES", "INVENTORY", "EMPLOYEES"):
        cur.execute(f"TRUNCATE TABLE {t}")

    stores, n = [], 1
    for region, names in REGIONS.items():
        for nm in names:
            stores.append((f"S{n:02d}", f"Bean & Brew {nm}", region, nm))
            n += 1
    cur.executemany("INSERT INTO STORES VALUES (%s,%s,%s,%s)", stores)

    # employees (personas first so they are stable for the demo)
    emps = [
        ("E001", "Maya Chen", "maya.chen@beanandbrew.example", "555-010-1001", "S01", "NORTH", "barista", 38000, date(2023, 3, 1)),
        ("E002", "Sam Rivera", "sam.rivera@beanandbrew.example", "555-010-1002", "S01", "NORTH", "store_manager", 62000, date(2020, 6, 15)),
        ("E003", "Priya Nair", "priya.nair@beanandbrew.example", "555-010-1003", "HQ", "NORTH", "regional_manager", 98000, date(2018, 1, 8)),
        ("E004", "Felix Weber", "felix.weber@beanandbrew.example", "555-010-1004", "HQ", "HQ", "finance_analyst", 85000, date(2019, 9, 2)),
        ("E005", "Hana Sato", "hana.sato@beanandbrew.example", "555-010-1005", "HQ", "HQ", "hr_admin", 79000, date(2017, 11, 20)),
    ]
    i = 6
    for sid, _nm, region, _c in stores:
        for role, lo, hi, cnt in (("barista", 30000, 42000, 4), ("shift_lead", 42000, 52000, 1)):
            for _ in range(cnt):
                f, l = rnd.choice(FIRST), rnd.choice(LAST)
                emps.append((f"E{i:03d}", f"{f} {l}", f"{f}.{l}{i}@beanandbrew.example".lower(),
                             f"555-020-{i:04d}", sid, region, role, rnd.randint(lo, hi),
                             date(2020, 1, 1) + timedelta(days=rnd.randint(0, 1700))))
                i += 1
    cur.executemany("INSERT INTO EMPLOYEES VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", emps)

    # inventory
    inv = []
    for sid, _n, region, _c in stores:
        for k, item in enumerate(["Espresso Beans", "Whole Milk", "Oat Milk", "Vanilla Syrup", "Caramel Syrup",
                                  "Matcha Powder", "Paper Cups 12oz", "Paper Cups 16oz", "Lids", "Muffins",
                                  "Croissants", "Breakfast Wraps", "Cold Brew Concentrate", "Sugar Sachets"]):
            reorder = rnd.randint(20, 60)
            inv.append((sid, region, f"SKU{k + 1:03d}", item, rnd.randint(5, 200), reorder, datetime(2026, 10, 10, 8)))
    cur.executemany("INSERT INTO INVENTORY VALUES (%s,%s,%s,%s,%s,%s,%s)", inv)

    # sales: 45 days, ~25 orders/day/store
    sales, oid = [], 1
    items = list(PRODUCTS.items())
    for d in range(45):
        day = datetime(2026, 8, 27) + timedelta(days=d)
        for sid, _n, region, _c in stores:
            for _ in range(rnd.randint(18, 32)):
                p, price = rnd.choice(items)
                q = rnd.randint(1, 3)
                ts = day + timedelta(minutes=rnd.randint(6 * 60, 20 * 60))
                sales.append((oid, sid, region, p, q, round(price * q, 2), ts))
                oid += 1
    cur.executemany("INSERT INTO SALES VALUES (%s,%s,%s,%s,%s,%s,%s)", sales)
    print(f"ok  seed: {len(stores)} stores, {len(emps)} employees, {len(inv)} inventory rows, {len(sales)} sales")


def main():
    env = load_env()
    conn = snowflake.connector.connect(
        account=env["SNOWFLAKE_ACCOUNT"], user=env["SNOWFLAKE_ADMIN_USER"],
        password=env["SNOWFLAKE_ADMIN_PASSWORD"], role="ACCOUNTADMIN")
    cur = conn.cursor()
    cur.execute("USE ROLE ACCOUNTADMIN")
    run_file(cur, "01_infra.sql")
    run_file(cur, "02_tables.sql")
    seed(cur)
    run_file(cur, "03_governance.sql")

    # role users: one dedicated, password-based LEGACY_SERVICE user per role (never the admin)
    cur.execute("USE ROLE ACCOUNTADMIN")
    for r in ROLES:
        key = f"SNOWFLAKE_BB_{r}_PASSWORD"
        pw = env.get(key) or secrets.token_urlsafe(18)
        if not env.get(key):
            save_env_var(key, pw)
        cur.execute(
            f"CREATE USER IF NOT EXISTS BB_{r}_SVC PASSWORD='{pw}' TYPE=LEGACY_SERVICE "
            f"DEFAULT_ROLE=BB_{r} DEFAULT_WAREHOUSE=BB_WH MUST_CHANGE_PASSWORD=FALSE")
        cur.execute(f"ALTER USER BB_{r}_SVC SET DEFAULT_ROLE=BB_{r} DEFAULT_WAREHOUSE=BB_WH")
        cur.execute(f"GRANT ROLE BB_{r} TO USER BB_{r}_SVC")
    print("ok  role users created (BB_*_SVC), admin user untouched")
    conn.close()


if __name__ == "__main__":
    main()
