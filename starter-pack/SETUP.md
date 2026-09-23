# Setup

End to end in about 45 minutes. Do the steps in order — step 2 is where almost
every problem originates, and step 3 proves it worked before you build anything
on top of it.

---

## Step 0 — Prerequisites

- Python 3.9+
- A Copilot Studio agent powered by the **standard harness**, with at least one
  test set
- Permission to create a Microsoft Entra app registration (or an admin who can)
- For the Dataverse repository: a Dataverse environment with a database, and
  rights to create tables

```bash
cd starter-pack
python -m pip install -r requirements.txt
cp .env.template .env
```

---

## Step 1 — Collect your IDs

In **Copilot Studio → your agent → Settings → Advanced → Details**:

| Value | Goes into |
|---|---|
| Environment ID | `ENVIRONMENT_ID` |
| Bot ID (Agent ID) | `BOT_ID` |

Put both in `.env`, along with your `TENANT_ID`.

---

## Step 2 — Microsoft Entra app registration

> **The single most important thing on this page.** The Power Platform API
> grants **delegated permissions only**. For a service principal, Microsoft's
> documented guidance is: *"don't use application permissions. Instead, after
> you create your app registration, assign it an RBAC role to grant scoped
> permissions."* A service principal will receive a token and still get
> **401/403** from the evaluation endpoints until that RBAC role is assigned.
> If you hit a 403 later, come back here first.

### 2a. Create the registration

```bash
az login
az ad app create --display-name "sp-copilot-eval-runner" --sign-in-audience AzureADMyOrg
# note the appId from the output
az ad sp create --id <app-id>
az ad app update --id <app-id> \
  --public-client-redirect-uris https://login.microsoftonline.com/common/oauth2/nativeclient
```

### 2b. Make the Power Platform API visible

The Power Platform API is not enabled in every tenant. Its fixed app ID is
`8578e004-a5c6-46e7-913e-12f58912df43`. If it does not appear in the API picker:

```powershell
Install-Module Microsoft.Graph -Scope CurrentUser -Repository PSGallery -Force
Connect-MgGraph
New-MgServicePrincipal -AppId 8578e004-a5c6-46e7-913e-12f58912df43 -DisplayName "Power Platform API"
```

or with the Azure CLI: `az ad sp create --id 8578e004-a5c6-46e7-913e-12f58912df43`

### 2c. Add permissions and consent

In the portal: **API permissions → Add a permission → APIs my organization
uses →** search the GUID above → add the Copilot Studio permissions your
scenario needs → **Grant admin consent**.

```bash
az ad app permission admin-consent --id <app-id>
```

### 2d. Choose your auth mode

| Mode | Use when | Extra requirement |
|---|---|---|
| `device_code` | First run, local dev, no browser on the box | Delegated consent (2c) |
| `interactive` | Local dev with a browser | Delegated consent (2c) |
| `azure_cli` | You are already `az login`-ed | Delegated consent (2c) |
| `client_secret` | Unattended pipelines | A client secret **and a Power Platform RBAC role assigned to the service principal** |

Start with `device_code` to prove everything works as *you*, then switch the
pipeline to `client_secret`. Debugging auth and API shape at the same time is
how a one-hour setup becomes a one-day setup.

---

## Step 3 — Prove it works

```bash
python evaluate.py --list-test-sets sample-agent
```

Expected: your test sets, with IDs, `state`, and case counts.

| What you see | What it means |
|---|---|
| The list | Auth and IDs are correct. Continue. |
| `401` / `403` | Token acquired but access denied. For a service principal → assign the RBAC role (step 2). For delegated → admin consent not granted. |
| `404` | `ENVIRONMENT_ID` or `BOT_ID` is wrong. Re-check Settings → Advanced → Details. |
| `No test set named ...` | Auth is fine. The display name in `config/agents.json` does not match — copy the exact name from this output. |

**Do not continue until this command works.** Everything downstream assumes it.

---

## Step 4 — Configure agents, suites and personas

Edit `config/agents.json`:

1. Replace the `sample-agent` block with your agent — `key`, `displayName`,
   `environmentId`, `botId`.
2. Set each suite's `testSetName` to the **exact** `displayName` from step 3.
3. Set thresholds. Suggested starting point:
   - Hard stop on any `ContentSafety` or security `Custom` failure
   - `CompareMeaning` ≥ 90%, `GeneralQuality` ≥ 85%
   - `maxInvalidRate` 10% — catches suite defects, not agent regressions
   - `minScoredResults` 1 — **leave this on.** A run that produced no gradeable
     results cannot demonstrate quality, and without this the gate would pass on
     an empty result set
   - `failOnUnknownStatus` true — **leave this on until SHAKEDOWN step 2 is
     done.** Unrecognised status tokens cannot be scored, so they cannot be
     gated on. Letting them through means the gate passes having verified
     nothing, precisely on the first run when unmapped tokens are most likely

   A hard-stop method configured in `failOnAnyFailureIn` that never produces a
   result in *any* suite is also treated as a failure — safety that was never
   evaluated is a coverage gap, not a clean run.

Values like `${ENVIRONMENT_ID}` are expanded from the environment, so the
config file stays safe to commit.

### Personas

For each persona you want to evaluate as:

1. Create a test account with exactly that persona's access.
2. Sign in to **Power Automate** as that account → **Connections** → add a
   **Microsoft Copilot Studio** connection.
3. Copy the ID from the URL:
   `.../connections/shared_microsoftcopilotstudio/{mcsConnectionId}/details`
4. Put it in `.env` as `MCS_CONN_<PERSONA>`.

Leave a persona's connection blank and that run executes **without
authentication** — a valid test, but a different one. Be deliberate.

> **Treat persona test sets as sensitive.** When Copilot Studio generates test
> cases it uses the connected account's credentials to reach knowledge sources
> and tools, so generated cases can contain data that account can see — and any
> maker with access to the agent can view the agent's test sets.

---

## Step 5 — First real run

```bash
python evaluate.py --suite smoke          # smallest useful run
python evaluate.py                        # the full matrix
python evaluate.py --no-gate --no-persist # collect only, never fail
```

Exit codes: `0` pass · `1` gate failed · `2` config/auth error · `3` a required
run errored.

Read the **top failure reasons** block in the console output before changing
anything. Clustered `aiResultReason` text usually points at one root cause
behind many failing cases.

### About result statuses

The exact status tokens the API returns are not exhaustively documented, so the
runner normalises them and **prints anything it does not recognise** rather
than guessing. If you see `unknown` results on your first run, open the JSON
output, look at `rawStatus`, and add the token to `PASS_TOKENS` / `FAIL_TOKENS`
in `eval_runner/pp_client.py`. One-line change, and it is the honest way to
handle an undocumented enum.

---

## Step 6 — Dataverse results repository

```bash
python dataverse/provision_schema.py --url https://yourorg.crm.dynamics.com --prefix cse --dry-run
python dataverse/provision_schema.py --url https://yourorg.crm.dynamics.com --prefix cse
```

Creates a publisher, a solution, two tables, their columns and the
relationship. Idempotent — safe to re-run after adding a column to
`schema.json`.

> **Choose your prefix now.** A table's customisation prefix comes from the
> solution publisher and **cannot be changed after creation**. Use your own
> (e.g. `acme`), not the sample `cse`.

Then set `DATAVERSE_URL` and `DATAVERSE_PREFIX` in `.env`, and export a real
versioned solution:

```bash
pac solution export --name CopilotStudioEvaluationFramework --managed false
```

---

## Step 7 — CI/CD

Copy the workflow you want into `.github/workflows/` in **your** repository:

| File | Purpose |
|---|---|
| `workflows/scheduled-eval.yml` | Nightly drift detection. **Start here.** |
| `workflows/release-gate.yml` | Deploy → evaluate → promote on pass |
| `azure/azure-pipelines.yml` | Azure DevOps equivalent |

They live in `workflows/` rather than `.github/workflows/` so they do not run
inside the starter-pack repo itself.

**Run the scheduled workflow for a week or two before you gate releases.** A
gate built on a signal nobody trusts yet gets switched off the first time it
blocks a release for the wrong reason.

---

## Step 8 — Power BI

See `powerbi/README.md`. Provision the repository, run at least one evaluation
so there is data, then build the model from `queries.m` and `measures.dax`.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `401` / `403` from evaluation endpoints | Service principal without a Power Platform RBAC role, or delegated consent not granted. |
| `404` on every call | Wrong `ENVIRONMENT_ID` / `BOT_ID`. |
| `No test set named X` | `testSetName` does not match the agent's test set `displayName`. Run `--list-test-sets`. |
| Everything returns `Invalid` | Test cases lack expected responses or keywords. Every method except *General quality* requires them. |
| Results say `unknown` | Unrecognised status token — see step 5. |
| Run never reaches a terminal state | Raise `pollTimeoutSeconds`. Large test sets take several minutes each. |
| Connector-based flows fail | The Microsoft Copilot Studio connector may be blocked by the environment's DLP policy. Check with your Power Platform admin. |
| Dataverse writes fail with a column error | Prefix mismatch between `DATAVERSE_PREFIX` and the prefix you provisioned with. |
