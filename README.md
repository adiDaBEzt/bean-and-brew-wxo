# Bean & Brew: Zero Trust Multi-Agent AI with watsonx Orchestrate, Snowflake RBAC & Keycloak OIDC

> **A Reference Architecture for Enterprise AI**: How to transform vulnerable "confused deputy" AI agents into reliable, trusted actors using a unified Master Router Agent in watsonx Orchestrate, self-hosted models (vLLM & Ollama on Modal), dynamic ephemeral Snowflake credentials, semantic long-term memory (Mem0), and OpenID Connect (Keycloak).

---

## ☕ The "Confused Deputy" Problem in Autonomous AI

When LLM-powered autonomous agents interact directly with enterprise databases and APIs, they commonly suffer from the **Confused Deputy** vulnerability:

1. **Broad Shared Credentials**: The agent connects using a single static database service user with excessive privileges.
2. **Untrusted Identity Propagation**: The agent trusts the LLM prompt or unverified user input to decide what records to return.
3. **Privilege Escalation**: Prompt injection or adversarial role-playing tricks the model into exfiltrating executive salaries or cross-store records.

### The Zero Trust Solution

This reference architecture implements an end-to-end **Zero Trust AI Architecture**:
- **Authentication**: Keycloak OpenID Connect (OIDC) authenticates users and mints cryptographically signed identity tokens containing verified roles (`barista`, `store_manager`, `regional_manager`, `finance_analyst`, `hr_admin`) and store scopes (`S01`, `NORTH`).
- **Master Operations Router Agent**: All employees interact with a single unified front door (`bb_master_agent`). The Master Agent inspects the user's verified identity context variables and delegates to specialized sub-agents (`bb_hr_agent`, `bb_finance_agent`) or local tools with strict RBAC enforcement.
- **Dynamic Ephemeral OAuth Tokens**: Per-session dynamic credentials issued by an internal Token Broker with a 300-second TTL and automatic revocation.
- **Mem0 Semantic Memory**: Per-user semantic memory stored in Qdrant and synthesized by Qwen on Modal, isolated by user identity.
- **Snowflake Native Data Governance**: Native **Row Access Policies (RAP)** and **Column Masking Policies** protect compensation data and restrict row access to the caller's store or region, even if the LLM attempts an unauthorized query.
- **Resilient Model Fallback**: Self-hosted **Qwen 2.5 7B** (vLLM on Modal serverless GPU) operates as primary with automatic failover to **Qwen 2.5 7B** (Ollama on Modal).

---

## 🏗️ Architecture

```mermaid
flowchart TD
    subgraph Client ["Client Layer"]
        User([Employee Persona]) -->|1. OIDC Login / Direct Grant| KC[Keycloak IdP :8080]
        KC -->|2. Signed JWT Token| UI[React + Vite Frontend :5173]
        UI -->|3. Session Cookie + Prompts| BFF[FastAPI BFF :8000]
    end

    subgraph SecurityBroker ["Zero Trust Security & Memory Broker"]
        BFF -->|Mint Ephemeral Creds| Broker[OAuth Token Broker (300s TTL)]
        BFF -->|User Memory Retrieval & Storage| Mem0[Mem0 + Qdrant Vector Store]
    end

    subgraph ControlPlane ["watsonx Orchestrate Control Plane"]
        BFF -->|4. Runs API + Signed Context| Master[bb_master_agent (Master Router)]
        Master --> POL{Model Fallback Policy}
        POL -->|Primary| vLLM[Modal vLLM Qwen 2.5 7B]
        POL -->|Fallback| Ollama[Modal Ollama Qwen 2.5 7B]
        
        Master -->|5. Authorized Delegation| SubAgents
        subgraph SubAgents ["Specialized Sub-Agents"]
            HRAgent[bb_hr_agent (HR Admin Only)]
            FinAgent[bb_finance_agent (Finance Only)]
        end
    end

    subgraph Execution ["Data & Tool Execution Layer"]
        Master & HRAgent & FinAgent --> Tools[Python Tools]
        Tools -->|6. Tool-Level RBAC Check| RBAC{Role Allowed?}
        RBAC -->|No| Denied[Access Denied]
        RBAC -->|Yes| SF[(Snowflake BEAN_BREW Database)]
        SF --> RAP[Row Access Policy: store_id = S01]
        SF --> Mask[Column Masking: Salary & PII]
    end
```

---

## 🛡️ Role-Based Access Matrix

| Role | Persona | Store / Region | Inventory | Sales Summaries | Employee Roster | Salary Compensation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Barista** | Maya Chen | Store S01 (North) | ✅ Read-only (Own Store) | ❌ Denied | ❌ Denied | ❌ Denied |
| **Store Manager** | Sam Rivera | Store S01 (North) | ✅ Read / Restock (Own Store) | ✅ Own Store Only | ✅ Own Team (Salary Masked) | ❌ Masked / Null |
| **Regional Manager**| Priya Nair | Region North | ✅ Regional Overview | ✅ Regional Sales | ❌ Denied | ❌ Denied |
| **Finance Analyst** | Felix Weber | Corporate HQ | ❌ Denied | ✅ Company-wide Aggregates | ❌ Denied | ✅ Statistical Aggregates Only |
| **HR Administrator**| Hana Sato | Corporate HQ | ❌ Denied | ❌ Denied | ✅ Full Roster Across All Stores | ✅ Full Unmasked Compensation |

---

## 🚀 Running the System

### 1. Services Overview
- **Keycloak IdP**: `http://localhost:8080` (Container: `bb-keycloak`)
- **FastAPI BFF**: `http://localhost:8000`
- **React Frontend**: `http://localhost:5173`

### 2. Start the Stack (If Restarting)
```bash
# 1. Start Keycloak container
cd infra && podman compose up -d && cd ..

# 2. Start FastAPI BFF
source venv/bin/activate
uvicorn bff.main:app --host 0.0.0.0 --port 8000

# 3. Start Frontend
cd frontend
npm run dev -- --host
```

---

## 🧪 Testing Personas & Scenarios

Open **[http://localhost:5173](http://localhost:5173)** in your browser.

### 👤 Persona 1: Maya Chen (Barista at Store S01)
1. Click **Maya Chen** on the login screen.
2. In the chat, click the suggestion chip: **"Check low inventory for my store (S01)"**.
   - **Result**: Fulfills inventory query scoped strictly to Store S01 (`Paper Cups`, `Whole Milk`, `Caramel Syrup`).
3. Click the suggestion chip: **"Can I see all employee salaries? (RBAC Block Test)"**.
   - **Result**: The Master Agent responds with **Access Denied**: Baristas cannot view salaries or employee records.
4. Open the **Security & Memory Inspector** drawer on the right:
   - Check **Tool Audit**: Inspect exact parameters passed to tools.
   - Check **OAuth Token**: View ephemeral Snowflake token issued for Maya with 300s TTL.
   - Check **Mem0**: View cross-session memory facts.

### 👤 Persona 2: Sam Rivera (Store Manager at Store S01)
1. Click **Switch User** and select **Sam Rivera**.
2. Click **"Summarize sales revenue for Store S01"**.
   - **Result**: Fulfills sales revenue for Store S01 ($1,477.35 over last 7 days).
3. Try asking for Store S02 sales: *"What are the sales for Store S02?"*
   - **Result**: Snowflake native Row Access Policy automatically restricts query execution to `store_id = 'S01'`.

### 👤 Persona 3: Hana Sato (HR Administrator)
1. Click **Switch User** and select **Hana Sato**.
2. Ask: *"Show me the employee roster for Store S01"*.
   - **Result**: Master Agent recognizes `hr_admin` role and automatically delegates to collaborator `bb_hr_agent`.
   - Returns unmasked employee details.

### 👤 Persona 4: Felix Weber (Finance Analyst)
1. Click **Switch User** and select **Felix Weber**.
2. Ask: *"Provide salary summary and budget breakdown for Store S01"*.
   - **Result**: Master Agent delegates to collaborator `bb_finance_agent`.
   - Returns statistical aggregates (headcount, average salary) from secure views without exposing raw PII.

---

## 📄 License
MIT License. Created for the IBM watsonx Orchestrate developer community.
