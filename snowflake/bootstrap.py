"""Create the Bean & Brew resources in a clean Snowflake lab account."""
import argparse
from getpass import getpass
import os
import pathlib
import random
import sys
from datetime import date, datetime, timedelta

import snowflake.connector
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
SQL_DIR = pathlib.Path(__file__).resolve().parent
KEY_DIR = SQL_DIR / "keys"

ROLES = ["BARISTA", "MANAGER", "REGIONAL", "FINANCE", "HR"]


def require_clean_account(cur):
    lab_resources = (
        ("DATABASES", "BEAN_BREW", {"BEAN_BREW"}),
        ("WAREHOUSES", "BB_WH", {"BB_WH"}),
        ("ROLES", "BB_%", {"BB_ADMIN", *(f"BB_{role}" for role in ROLES)}),
        ("USERS", "BB_%", {f"BB_{role}_SVC" for role in ROLES}),
    )
    conflicts = []
    for object_type, pattern, expected_names in lab_resources:
        cur.execute(f"SHOW {object_type} LIKE '{pattern}'")
        name_index = next(index for index, field in enumerate(cur.description) if field[0].lower() == "name")
        matches = sorted({row[name_index] for row in cur.fetchall()} & expected_names)
        if matches:
            conflicts.append(f"{object_type.lower()}: {', '.join(matches)}")
    if conflicts:
        raise SystemExit(f"Existing Snowflake objects block a fresh lab setup ({'; '.join(conflicts)}). See lab/01-snowflake.md.")


def service_public_keys():
    KEY_DIR.mkdir(mode=0o700, exist_ok=True)
    public_keys = {}
    for role in ROLES:
        private_path = KEY_DIR / f"{role.lower()}.p8"
        if private_path.exists():
            private_key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
            if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 2048:
                raise SystemExit(f"{private_path.name} must contain an RSA private key of at least 2048 bits.")
        else:
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            private_pem = private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            with os.fdopen(os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as private_file:
                private_file.write(private_pem)
        private_path.chmod(0o600)

        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_path.with_suffix(".pub").write_bytes(public_pem)
        public_keys[role] = "".join(public_pem.decode("ascii").splitlines()[1:-1])
    return public_keys


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mfa", action="store_true", help="Prompt for a Snowflake authenticator app passcode.")
    args = parser.parse_args()
    if not ENV_FILE.is_file():
        raise SystemExit("Create .env from .env.example before running this lab step.")
    env = dotenv_values(ENV_FILE, interpolate=False)
    account = env.get("SNOWFLAKE_ACCOUNT")
    user = env.get("SNOWFLAKE_ADMIN_USER")
    if not account or not user or account == "your-account-id" or user == "YOUR_ADMIN":
        raise SystemExit("Set SNOWFLAKE_ACCOUNT and SNOWFLAKE_ADMIN_USER in .env before running this lab step.")

    login = {
        "account": account,
        "user": user,
        "password": env.get("SNOWFLAKE_ADMIN_PASSWORD") or getpass("Snowflake admin password: "),
        "role": "ACCOUNTADMIN",
        "login_timeout": 60,
    }
    if args.mfa:
        login["authenticator"] = "username_password_mfa"
        login["passcode"] = getpass("Snowflake MFA passcode: ").strip()

    with snowflake.connector.connect(**login) as conn, conn.cursor() as cur:
        cur.execute("USE ROLE ACCOUNTADMIN")
        require_clean_account(cur)
        public_keys = service_public_keys()
        # CREATE without IF NOT EXISTS claims the lab name before any other change.
        cur.execute("CREATE DATABASE BEAN_BREW")
        run_file(cur, "01_infra.sql")
        run_file(cur, "02_tables.sql")
        seed(cur)
        run_file(cur, "03_governance.sql")

        cur.execute("USE ROLE ACCOUNTADMIN")
        for role, public_key in public_keys.items():
            cur.execute(
                f"CREATE USER BB_{role}_SVC TYPE=SERVICE DEFAULT_ROLE=BB_{role} "
                "DEFAULT_WAREHOUSE=BB_WH RSA_PUBLIC_KEY=%s",
                (public_key,),
            )
            cur.execute(f"GRANT ROLE BB_{role} TO USER BB_{role}_SVC")
    print(f"ok  created {len(ROLES)} service users with RSA keys in snowflake/keys/")


if __name__ == "__main__":
    main()
