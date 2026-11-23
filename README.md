# Bean & Brew | Governed AI agents lab

Build and test a coffee-chain operations assistant with IBM watsonx Orchestrate, Snowflake, and Keycloak. You will provision synthetic inventory and employee data, deploy three agents, then compare what a barista, a store manager, and an HR administrator can see.

**Time** · 60–90 minutes with accounts ready

**Machine** · Mac or Linux. The lab runs Keycloak directly on Java and uses loopback ports 8080, 8000, and 5173. The standalone path needs no container runtime or hypervisor.

## Prerequisites

| What you need | What it does |
| --- | --- |
| Git, Python 3.12, and Node.js 22.12 or newer | Clone the repo and run the FastAPI and Vite apps. |
| Java 25 and an approved standalone Keycloak 26.8.2 distribution | Run the local identity provider. Use the zip or tar archive from the [Keycloak downloads page](https://www.keycloak.org/downloads). |
| A dedicated Snowflake Enterprise Edition trial or lab account | Create the synthetic dataset, service users, row access policy, and masking policies. You need an administrator who can use `ACCOUNTADMIN`. |
| An IBM Cloud watsonx Orchestrate instance and IAM API key | Create connections and import tools. You need rights to import and deploy agents in the intended workspace. |

Use a dedicated lab account and synthetic data. Keep the local services on loopback. The `.env` file, Snowflake private keys, and generated Keycloak realm contain secrets and are ignored by Git.

## 1. Clone the lab and install dependencies

```bash
git clone --branch codex/bean-and-brew-lab https://github.com/adiDaBEzt/bean-and-brew-wxo.git
cd bean-and-brew-wxo
python3.12 -m venv venv
venv/bin/python -m pip install -r bff/requirements.txt 'ibm-watsonx-orchestrate==2.10.0'
npm ci --prefix frontend
cp -n .env.example .env
chmod 600 .env
```

Install the Python requirements and ADK together so pip can resolve Snowflake and IBM SDK dependencies in one pass. This includes `snowflake-connector-python`, `langgraph`, and the SQLite checkpointer.

**Checkpoint**

```bash
venv/bin/python -m pip check
venv/bin/python -c 'import snowflake.connector; from langgraph.checkpoint.sqlite import SqliteSaver; print("Python dependencies OK")'
venv/bin/orchestrate --version
```

## 2. Provision Snowflake

Follow [01 · Set up Snowflake](lab/01-snowflake.md) to find the account identifier, create the synthetic tables and policies, and generate five RSA key pairs. The bootstrap stops if any of the lab’s Snowflake names already exist.

**Checkpoint** · The bootstrap reports five service users. The lab policy test exercises store and region scope, salary masking, and raw-table grants.

## 3. Deploy the agents

Follow [02 · Deploy in watsonx Orchestrate](lab/02-orchestrate.md) to find the service URL and IAM key, configure Draft and Live Snowflake connections, and import the HR, finance, and master agents. The YAML uses `style: react` for ADK 2.10.0 and defaults to Claude Sonnet 4.6 when the tenant offers it. Save the master agent ID in `.env`.

**Checkpoint** · The master is Live with its collaborators, and `WXO_MASTER_AGENT_ID` points at your tenant’s `bb_master_agent`.

## 4. Run the app locally

Follow [03 · Start Keycloak and the app](lab/03-run-locally.md) to generate the realm, start the standalone Java server, and launch FastAPI and Vite in separate terminals.

**Checkpoint** · Keycloak discovers the `bean-brew` realm, `/health` returns `ok`, and Maya signs in as a barista at `S01`. [Open the app](http://127.0.0.1:5173/)

## 5. Run the exercises

Follow [04 · Test role-based access](lab/04-exercises.md) for exact prompts and expected results. Start with Maya’s low-inventory lookup, inspect the tool response, then ask Sam and Hana the same roster question.

**Checkpoint** · `bb_get_inventory` returns only S01 rows. Sam’s roster result has masked salary and contact fields. Hana’s result shows those fields. For a direct database check, use the Snowflake policy tests in step 2.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `No module named 'snowflake'` or `langgraph.checkpoint.sqlite` | Check that you are using `venv/bin/python`. Rerun the combined Python dependency install in step 1. |
| Agent import says `react_core` is invalid | Use `style: react` and import HR and finance before the master. Confirm that you are on the lab branch. |
| Orchestrate cannot find the agent, or the backend points to the wrong agent | Get the ID for `bb_master_agent` from the active lab environment and set `WXO_MASTER_AGENT_ID`. Restart FastAPI after editing `.env`. |
| Podman says the machine already exists, or its socket refuses the connection | Follow step 4’s standalone Java path. It works without starting a Podman machine. |
| Keycloak returns an error at sign-in | Check the `bean-brew` discovery endpoint and that the `bb-web` client allows direct access grants. Match the installed realm’s credentials to `.env`. The app reports sign-in errors on the persona picker. |
| The chat stays on **Master Agent reasoning & evaluating Zero Trust policies...** | Give a first lookup about 20–30 seconds. The app shows a timeout or an empty-reply message if appropriate. If the service reports an error, check the FastAPI terminal and the Live deployment’s tool connections. |
| The audit button seems to do nothing on a narrow window | Click **Inspect Agent Routing & Tool Audit** under a completed response. The inspector opens over the chat on narrow screens and scrolls to the trace on wider screens. |
| A local port is already in use | Use `lsof -nP -iTCP:8080 -iTCP:8000 -iTCP:5173 -sTCP:LISTEN` on macOS. Reuse a healthy lab instance or stop its own terminal with `Ctrl+C`, then restart it. |

## What the lab demonstrates

Keycloak provides identity claims to the local backend. The backend passes role and store context to the Orchestrate run. The master agent routes requests to tools and collaborators. Python tools check a role allow-list and select a role-specific Snowflake connection. Snowflake grants, row access rules, and column masking control the resulting queries. The demo session marker in the UI is app metadata. Snowflake service users authenticate with RSA keys.

This lab uses a developer-only Keycloak realm with a shared synthetic-user password and direct grants. Tool role and scope inputs are part of the model-visible tool schema. For a production design, derive these values from trusted runtime identity at the point of execution and enforce the scope independent of the model.

## Stop the lab

Press `Ctrl+C` in the frontend, backend, and Keycloak terminals. Use the cloud cleanup notes in [01 · Snowflake](lab/01-snowflake.md) and [02 · Orchestrate](lab/02-orchestrate.md) when you are finished with the lab resources.

Original project and license notice · [Bean & Brew upstream README](https://github.com/adiDaBEzt/bean-and-brew-wxo/tree/main#readme) (MIT).
