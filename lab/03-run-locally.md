# 03 · Start Keycloak and the app

**Goal** · Sign in through Keycloak and reach your Live Orchestrate agent from the local UI.

Complete [02 · Deploy in watsonx Orchestrate](02-orchestrate.md) and set `WXO_MASTER_AGENT_ID` before starting FastAPI. Run commands from the repo root unless stated otherwise.

## 1. Generate the demo realm

```bash
venv/bin/python infra/keycloak/gen_realm.py
```

The generator fills any blank `KEYCLOAK_CLIENT_SECRET`, `DEMO_USER_PASSWORD`, and `BFF_JWT_SECRET` in `.env`. It writes `infra/keycloak/realm-bean-brew.json` with five users and enables direct access grants for the confidential `bb-web` client because the backend exchanges the demo persona’s credentials at the Keycloak token endpoint. Keep `.env` and the generated file private.

## 2. Run standalone Keycloak in Terminal 1

1. Extract the approved Keycloak 26.8.2 archive in Finder or your file manager.
2. Open the extracted folder and create a `data/import` folder path if it is missing. From the lab repo, copy `infra/keycloak/realm-bean-brew.json` into that folder and rename the copy to `bean-brew-realm.json`. Keep the copy in your private local Keycloak folder.
3. Open a terminal. Set `KEYCLOAK_DIR` to your extracted folder. The command below selects Java 25 on macOS. On Linux, set `JAVA_HOME` to the path of your approved Java 25 installation.

   ```bash
   export KEYCLOAK_DIR="/absolute/path/to/keycloak-26.8.2"
   export JAVA_HOME="$(/usr/libexec/java_home -v 25)"
   "$KEYCLOAK_DIR/bin/kc.sh" start-dev --import-realm \
     --http-host=127.0.0.1 --http-port=8080
   ```

Keep this terminal open. Keycloak should log `Realm 'bean-brew' imported` on the first start. Reuse the same `.env` and Keycloak installation for later runs. Startup import skips an existing realm. If its credentials differ, use a fresh standalone extraction dedicated to the lab, or have the lab owner update that realm. [Keycloak realm import](https://www.keycloak.org/server/importExport)

**Checkpoint** · Open the realm discovery page in your browser. You should see JSON with the issuer `http://127.0.0.1:8080/realms/bean-brew`. [Open Keycloak discovery](http://127.0.0.1:8080/realms/bean-brew/.well-known/openid-configuration)

## 3. Run FastAPI in Terminal 2

```bash
venv/bin/uvicorn bff.main:app --host 127.0.0.1 --port 8000
```

Open the health page in your browser. The JSON should include `"status":"ok"`. [Open backend health](http://127.0.0.1:8000/health)

## 4. Run Vite in Terminal 3

```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --strictPort
```

Open the app, select **Maya Chen**, and confirm the header displays `barista` and `Store S01`. The backend requires a successful Keycloak response with a Bean & Brew role. If sign-in fails, the persona picker displays the error. [Open Bean & Brew](http://127.0.0.1:5173/)

**Next** · [04 · Test role-based access](04-exercises.md)
