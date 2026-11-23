# 04 · Test role-based access

**Goal** · Compare the tool results two employees get for the same question and confirm what Snowflake enforces. Use the synthetic data seeded in [step 2](01-snowflake.md).

## Exercise 1 · Inventory and a compensation request as Maya

1. Select **Maya Chen**. Confirm the header says `barista` and `Store S01`.
2. Click **Check low inventory for my store (S01)**. Allow about 20–30 seconds for the first live request.
3. Click **Inspect Agent Routing & Tool Audit**. In **Execution Audit**, look for `bb_get_inventory` followed by its tool response. Expand **View Raw Trace JSON** and check that every returned `store_id` is `S01`. A fresh seed returns six low-stock rows. `SKU007` (Paper Cups 12oz) has 20 on hand and a reorder level of 60.
4. Ask **Can I see all employee salaries?** Maya should get a denial. The read-only role has no employee table grant.

**Record** · How many low-stock rows did the tool return? What role and store appear in the inspector’s **Identity & Token** tab?

## Exercise 2 · The same roster question as Sam and Hana

Click **Switch User → Sam Rivera**, then send this prompt:

```text
Show the employee roster for Store S01. Include names, roles, and any salary or contact fields I’m allowed to see.
```

Open the audit for `bb_get_team_roster`. In its raw result, check that the roster contains S01 employees, salary values are `null`, and contact fields are masked. The agent may omit masked fields from its prose.

Switch to **Hana Sato** and paste the exact same prompt. Look for a roster result with unmasked salary and contact fields. The HR agent is configured as a collaborator and has broader roster access. When comparing the raw result, look for S01 rows. The HR tool may return rows for additional stores.

**Record** · Compare one S01 employee in the two responses. Which fields changed, and which Snowflake policy explains each change?

## Exercise 3 · Finance aggregates

Switch to **Felix Weber** and send:

```text
Show salary headcount, average salary, and total payroll by region and role.
```

In the audit, look for `bb_get_salary_summary`. Identify the three aggregate measures. Finance reads secure reporting views. Confirm the grant boundary with the direct Snowflake policy test in [01 · Set up Snowflake](01-snowflake.md).

## Optional · Update a preference

As Maya, say **I prefer oat milk**, then **I prefer almond milk now**. Open **Memory** in the inspector and check the stored milk preference. Switch away and back, then ask **What milk do I prefer?** The app stores preferences per user in local SQLite.

## Instructor talk track

- “Maya is signed in as a barista at S01. Her answer is backed by the `bb_get_inventory` Snowflake tool.”
- “I’ll ask for the same roster as Sam and Hana. Watch how the returned fields change with the signed-in role.”
- “The tool trace lets us connect an answer to a query result. The direct Snowflake tests let us verify database enforcement separately from what the model says.”

When finished, press `Ctrl+C` in the three local terminals. Return to the [lab overview](../README.md#stop-the-lab) for cloud cleanup.
