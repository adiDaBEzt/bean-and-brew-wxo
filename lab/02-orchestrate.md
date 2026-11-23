# 02 · Deploy in watsonx Orchestrate

**Goal** · Give each lab role its own Snowflake connection, deploy the three agents, and copy the master agent ID into the app configuration. Use a dedicated IBM Cloud Orchestrate instance or approved lab workspace. The connection IDs are shared within an instance.

## 1. Get the instance URL and IAM key in Orchestrate

1. Open your watsonx Orchestrate instance. In the profile menu, select **Settings → API details**.
2. Copy **Service instance URL** into `WXO_URL` in your local `.env` file. Include the `/instances/…` part.
3. Select **Generate API key**. Save the IAM key in `WXO_API_KEY` in `.env`. You’ll also enter it privately when the ADK asks you to sign in. [IBM Cloud ADK setup](https://ibm.github.io/EEL-agentic-ai-bootcamp/labs/environment-setup-lab/wxo-client-setup/)

## 2. Set up the five Snowflake connections

Complete [01 · Set up Snowflake](01-snowflake.md) first. Each connection uses the account identifier in `SNOWFLAKE_ACCOUNT` and a dedicated service identity.

| Connection ID | Snowflake user | Key file |
| --- | --- | --- |
| `bb_sf_barista` | `BB_BARISTA_SVC` | `snowflake/keys/barista.p8` |
| `bb_sf_manager` | `BB_MANAGER_SVC` | `snowflake/keys/manager.p8` |
| `bb_sf_regional` | `BB_REGIONAL_SVC` | `snowflake/keys/regional.p8` |
| `bb_sf_finance` | `BB_FINANCE_SVC` | `snowflake/keys/finance.p8` |
| `bb_sf_hr` | `BB_HR_SVC` | `snowflake/keys/hr.p8` |

1. From the main menu, open **Manage → Security → Connections → Custom**.
2. Add a custom connection. Enter the exact **Connection ID** from the table. You can use the same value for **Display name**.
3. For **Draft**, choose **Key Value Pair** authentication and **Team** credentials. Save the configuration, then add the credential entries below in that environment’s credential editor.

   | Key | Value |
   | --- | --- |
   | `account` | The `organization-account` value from `SNOWFLAKE_ACCOUNT`. |
   | `user` | The Snowflake user from the table. |
   | `private_key` | The entire matching `.p8` file, preserving its line breaks and PEM header and footer. |

4. Save the credentials. Repeat the configuration and credentials for **Live**, then repeat for the other roles. The **Custom** list should show all five connections configured with credentials in both environments. Use the shortcut below if your credential editor cannot preserve PEM line breaks. [IBM connection management](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=credentials-creating-managing-connections) · [Draft and Live connections](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=credentials-connections-across-environments-deployments)

## 3. Sign in to the ADK once and batch-import the files

IBM’s ADK imports the six Python tools and the supplied YAML definitions, including the agents’ context-variable settings. Run these commands from the repo root. Enter the IAM key when prompted. If `bean-brew-lab` is already registered, run only the activate command. [Python tool import](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=agents-managing-tools) · [Defining agent context variables](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=behavior-adding-instructions-agents)

```bash
instance_url="$(venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["WXO_URL"].rstrip("/"))')"
venv/bin/orchestrate env add --name bean-brew-lab --url "$instance_url" --type ibm_iam
venv/bin/orchestrate env activate bean-brew-lab
```

If you configured the five connections in the UI, import the six tools in one command:

```bash
venv/bin/orchestrate tools import --kind python --safe \
  --file wxo/tools/bb_tools.py --requirements-file wxo/tools/requirements.txt \
  --app-id bb_sf_barista --app-id bb_sf_manager --app-id bb_sf_regional \
  --app-id bb_sf_finance --app-id bb_sf_hr
```

<details>
<summary>Fast setup for all ten connection environments and the six Python tools</summary>

If you skipped the manual connection setup, run `bash wxo/scripts/02_connections_tools.sh` in place of the tool import command above. After ADK sign-in, it reads the account and keys from disk, creates the Draft and Live credentials for all five roles, and imports the tools. A fresh run has no further prompts. If you retry and see an update prompt, check that it names a lab tool before continuing.

</details>

Import the two collaborator definitions first so the master can reference them by name. The imports are unattended on a fresh workspace. On a retry, **safe** mode asks before updating an existing agent.

```bash
venv/bin/orchestrate agents import --safe --file wxo/agents/bb_hr_agent.yaml &&
venv/bin/orchestrate agents import --safe --file wxo/agents/bb_finance_agent.yaml &&
venv/bin/orchestrate agents import --safe --file wxo/agents/bb_master_agent.yaml
```

**Checkpoint** · In Orchestrate, open **Build → All tools** and verify that `bb_get_inventory`, `bb_get_team_roster`, and `bb_get_salary_summary` are listed. Open **All agents** and look for **Bean & Brew HR Operations Agent**, **Bean & Brew Finance & Analytics Agent**, and **Bean & Brew Master Operations Agent**. Select the workspace used by the imports if your tenant has more than one.

## 4. Review the model and deploy in Agent Builder

1. Open the **Bean & Brew HR Operations Agent** from **Build → All agents**. Check the **AI model** setting. The supplied YAML selects **Claude Sonnet 4.6 on Amazon Bedrock** (`bedrock/us.anthropic.claude-sonnet-4-6`). If your tenant marks it unavailable, choose a permitted model with tool calling and save. Repeat the model check for each agent. [IBM model selection](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=agents-choosing-ai-model-agent)
2. Select **Deploy**, review the **Pre-deployment Summary**, and confirm the deployment. Resolve any missing **Live** credentials in the connection’s configuration before retrying.
3. Deploy **Bean & Brew Finance & Analytics Agent** next. Then open **Bean & Brew Master Operations Agent**, verify both collaborators are listed in its configuration, and deploy it last. Each agent should show as **Live**. [IBM deployment steps](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=deploying-agents-live-environment)

## 5. Copy the master agent ID in the UI

1. On **Bean & Brew Master Operations Agent**, go to **Channels → Embedded agent** and select **Live**.
2. Copy the generated snippet into a local scratch editor. In `chatOptions`, copy the UUID next to `agentId` into `WXO_MASTER_AGENT_ID` in `.env`. The app uses only this UUID from the snippet. [Where the UI shows the agent ID](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=applications-embedding-agent-web)
3. If the embed panel is unavailable in your tenant, run `venv/bin/orchestrate agents list --kind native --verbose` and copy the `id` for the object whose `name` is `bb_master_agent`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| The ADK reports an expired token | Run `venv/bin/orchestrate env activate bean-brew-lab` and enter your IAM key privately. |
| The fast setup reports the wrong environment | Compare the service URL used during ADK environment registration with `WXO_URL` in `.env`. |
| A tool reports missing credentials | Open the matching connection in **Manage → Security → Connections**. Check both environments and match the `.p8` file to the right Snowflake user. |
| Import fails because the model is unavailable | Run `venv/bin/orchestrate models list --all --raw` to find an allowed model ID. In your editor, change `llm` in the three YAML files under `wxo/agents/`, then retry the imports. |
| Import reports `react_core` is invalid | Use this lab branch and verify that the YAML files contain `style: react`. |

## Clean up a dedicated lab workspace

When you finish the lab, use Agent Builder to undeploy and remove the master first, then the two collaborators. In **All tools**, remove the six lab tools. In **Manage → Security → Connections**, remove their five `bb_sf_*` connections. Confirm each item belongs to your lab before removing it.

**Next** · [03 · Start Keycloak and the app](03-run-locally.md)
