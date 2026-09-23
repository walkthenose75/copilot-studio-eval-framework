# Shakeout runbook

**Purpose:** convert this from "written against docs" to "proven in our tenant."

Work top to bottom. Each step has a **command**, an **expected result**, and a
**what to fix** column. Do not skip ahead — step 2 finds the problems that make
step 3 confusing if you hit them together.

Record every finding in the table at the bottom, and update the verified/
unverified table in `.github/copilot-instructions.md` as you go.

Target environment: use a **sandbox**, never production. A dedicated
development or UAT sandbox is appropriate.

---

## Step 0 — Environment

```bash
cd starter-pack
python -m pip install -r requirements.txt
cp .env.template .env
```

Fill in `.env`: `TENANT_ID`, `CLIENT_ID`, `ENVIRONMENT_ID`, `BOT_ID`.
`ENVIRONMENT_ID` and `BOT_ID` come from Copilot Studio →
**Settings → Advanced → Details**.

Set `AUTH_MODE=device_code` for the shakeout. Do **not** start with
`client_secret` — debugging auth and API shape simultaneously wastes hours.

**Prerequisite:** the target agent must already have at least one test set.
If it has none, create one from `testsets/smoke.csv` first — see
`testsets/README.md`.

---

## Step 1 — Prove auth and IDs

```bash
python evaluate.py --list-test-sets sample-agent
```

| Result | Meaning | Fix |
|---|---|---|
| Test sets listed with IDs and `state` | Auth + IDs correct. Continue. | — |
| `401` / `403` | Token acquired, access denied | Delegated: grant admin consent. Service principal: assign a **Power Platform RBAC role** — app permissions alone are never enough |
| `404` | Wrong `ENVIRONMENT_ID` or `BOT_ID` | Re-copy from Settings → Advanced → Details |
| `No test set named ...` | Auth fine, naming mismatch | Copy the exact `displayName` into `config/agents.json` |

**Do not continue until this returns your test sets.**

**Record:** paste the raw output into `samples/01-testsets.json`.
This is the first real response shape captured — compare its fields against
what `list_test_sets()` expects (`id`, `displayName`, `state`, `totalTestCases`).

---

## Step 2 — First real run, and fix the status tokens

This is the highest-value step. It is where the guesses get corrected.

```bash
python evaluate.py --suite smoke --no-persist --out results
```

Then inspect the captured response:

```bash
python - <<'PY'
import json, glob, collections
f = sorted(glob.glob('results/results-*.json'))[-1]
d = json.load(open(f))
tokens = collections.Counter()
methods = collections.Counter()
for e in d['executions']:
    for r in e['records']:
        tokens[(r['rawStatus'], r['outcome'])] += 1
        methods[r['method']] += 1
print('STATUS TOKEN -> CLASSIFIED AS:')
for (raw, out), n in tokens.items():
    flag = '  <-- UNMAPPED' if out == 'unknown' else ''
    print(f'  {raw!r:28} -> {out:8} x{n}{flag}')
print('\nMETHOD NAMES RETURNED BY THE API:')
for m, n in methods.items():
    print(f'  {m!r} x{n}')
PY
```

| Finding | Action |
|---|---|
| Any `UNMAPPED` token | Add it to `PASS_TOKENS` / `FAIL_TOKENS` / `INVALID_TOKENS` in `eval_runner/pp_client.py`. **This is expected on first run.** |
| Method names differ from config | Update `thresholds` keys in `config/agents.json` to the real names |
| All results `invalid` | Test cases lack expected answers/keywords. Every method except *General quality* requires them |
| `score` always `null` | The field may not exist, or sits elsewhere. Inspect a raw run (below) before changing the parser |

**Capture a raw, unparsed run** — this is the artifact that resolves every
remaining response question:

```bash
python - <<'PY'
import os, json
from eval_runner.auth import provider_from_env
from eval_runner.config import load_config
from eval_runner.pp_client import EvaluationClient
cfg = load_config('config/agents.json'); a = cfg.agent('sample-agent')
c = EvaluationClient(provider_from_env(), a.environment_id, a.bot_id)
runs = c.list_runs()
os.makedirs('samples', exist_ok=True)
json.dump(runs, open('samples/02-testruns-list.json','w'), indent=2)
if runs:
    rid = runs[0].get('id') or runs[0].get('runId')
    json.dump(c.get_run(rid), open('samples/03-testrun-detail.json','w'), indent=2)
    print('captured detail for run', rid)
PY
```

Open `samples/03-testrun-detail.json` and confirm against `iter_metrics()`:
- Is it `testCasesResults[].metricsResults[].result`?
- Where do `status`, `aiResultReason`, `errorReason` actually live?
- What are the real `state` values? Update `NON_TERMINAL_STATES`.

**Then re-run step 2 and confirm zero `unknown` results.**

---

## Step 3 — Published vs draft

Confirm `runOnPublishedBot` behaves as expected, because a release gate depends
on it.

1. Run the smoke suite with `"runOnPublishedBot": true` in `config/agents.json`.
2. Make a visible change to the agent in Copilot Studio — **do not publish**.
3. Re-run. Results should be **unchanged** (it evaluated the published agent).
4. Publish, re-run. Results should now reflect the change.

If step 3 shows the change before publishing, the flag is not doing what the
manifest describes — record it and set the expectation accordingly. This is a
documented-but-unverified behaviour and is worth ten minutes to confirm.

---

## Step 4 — Personas

1. Create a test account per persona with genuinely different access.
2. As each account, sign in to **Power Automate → Connections**, add a
   **Microsoft Copilot Studio** connection.
3. Copy each `mcsConnectionId` from the URL:
   `.../connections/shared_microsoftcopilotstudio/{mcsConnectionId}/details`
4. Put them in `.env` as `MCS_CONN_*`.

```bash
python evaluate.py --suite security --no-persist
```

**The test that matters:** the same test case must produce *different* outcomes
across personas. If every persona returns identical results, either the
questions are not identity-sensitive or the profile is not being applied —
both are findings worth having before the customer asks.

---

## Step 5 — Dataverse repository

```bash
python dataverse/provision_schema.py --url https://<org>.crm.dynamics.com --prefix <yours> --dry-run
python dataverse/provision_schema.py --url https://<org>.crm.dynamics.com --prefix <yours>
```

> Pick your own prefix. It **cannot be changed after the tables are created.**

Then set `DATAVERSE_URL` / `DATAVERSE_PREFIX` in `.env` and run with
persistence:

```bash
python evaluate.py --suite smoke
```

**The known risk here is the lookup binding.** Dataverse's OData endpoint is
case-sensitive on navigation property names, and lookups created via the Web
API are a documented source of "Undeclared property" runtime errors. If the
metric rows fail to insert, verify the real navigation property name:

```bash
python - <<'PY'
import os, requests
from eval_runner.auth import TokenProvider
url = os.environ['DATAVERSE_URL'].rstrip('/'); pfx = os.environ.get('DATAVERSE_PREFIX','cse')
tp = TokenProvider(mode='device_code', tenant_id=os.environ['TENANT_ID'],
                   client_id=os.environ['CLIENT_ID'], scope=f'{url}/.default')
r = requests.get(f"{url}/api/data/v9.2/{pfx}_metricresults?$top=1", headers=tp.header(), timeout=60)
for k, v in r.json().get('value', [{}])[0].items():
    if 'associatednavigationproperty' in k:
        print('USE THIS FOR @odata.bind ->', v)
PY
```

Whatever that prints is the exact key `dataverse.py` must use. Correct
`persist_execution()` if it differs.

Confirm: one row in `<prefix>_evaluationruns`, one row per test case × method in
`<prefix>_metricresults`, correctly related.

Then export a real solution:

```bash
pac solution export --name CopilotStudioEvaluationFramework --managed false
```

---

## Step 6 — Power BI

Follow `powerbi/README.md`.

| Known risk | Fix |
|---|---|
| `CommonDataService.Database` not recognised | Switch the `DataverseDb` helper to `Dataverse.Database` (Sept 2024+ builds) |
| Any DAX measure errors | 25 measures, none previously evaluated. `Pass Rate (Previous Run)` uses `ALLEXCEPT` and is the most likely to need adjustment |

Sanity check: the numbers on the report must match the console output from
step 2 for the same run. If they disagree, trust the console — it reads the
API directly.

---

## Step 7 — Pipeline

1. Copy `workflows/scheduled-eval.yml` → `.github/workflows/` in your repo.
2. Set repo variables and `PP_CLIENT_SECRET`.
3. **Switch to `client_secret` auth only now.** If it 401s where device code
   worked, the service principal is missing its Power Platform RBAC role —
   that is the expected cause.
4. Run it manually (`workflow_dispatch`) before trusting the schedule.
5. Only after it runs clean for several days, add `release-gate.yml`.

---

## Findings log

Fill this in as you go. It is the handover artifact.

| Step | Expected | Actual | Code change made |
|---|---|---|---|
| 1 | Test sets listed | | |
| 2 | Zero unknown tokens | | |
| 3 | Published ≠ draft | | |
| 4 | Personas diverge | | |
| 5 | Rows persisted | | |
| 6 | Report matches console | | |
| 7 | Pipeline green | | |

---

## Definition of done

- [ ] Steps 1–7 complete against a real tenant
- [ ] Zero `unknown` status tokens on a full run
- [ ] `@odata.bind` binding confirmed against live metadata
- [ ] Power BI numbers reconcile with console output
- [ ] Verified/unverified table in `.github/copilot-instructions.md` updated
- [ ] Findings log above filled in

Only then is it accurate to describe this as proven.
