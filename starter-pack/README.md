# Copilot Studio Evaluation Framework — Starter Pack

A working implementation of the build layer described in the
[framework briefing](../docs/index.html): trigger surface, quality gate,
results repository, CI/CD, and reporting.

Built for agents powered by the Copilot Studio **standard harness**.

---

## What's in the box

| Component | What it is | Status |
|---|---|---|
| `evaluate.py` + `eval_runner/` | Python runner over the documented `makerevaluation` API — persona matrix, parallel runs, polling, gating | Customer-built |
| `dataverse/` | Schema + idempotent provisioning script for the results repository | Customer-built |
| `testsets/` | Seed CSVs for smoke, regression, security-persona and scenario suites | Import-ready |
| `config/agents.json` | Agents, suites, personas and thresholds — data, not code | Configuration |
| `workflows/` | GitHub Actions: release gate and scheduled evaluation | Customer-built |
| `azure/` | Azure DevOps pipeline equivalent, plus what Azure is actually needed for | Customer-built |
| `powerbi/` | M queries + DAX measures for the three governance report pages | Customer-built |

Everything calls documented, supported interfaces. Nothing here is a private
API or an unsupported workaround.

---

## Status — read before sharing

Request shapes are **verified against Microsoft's published Copilot Studio
connector definition**. Response handling is **written defensively and not yet
verified against a live tenant.**

- `.github/PROVENANCE.md` — exactly what is verified, how, and what is not
- `SHAKEDOWN.md` — the runbook that closes the gap (~3 hours, one sandbox)
- `.github/copilot-instructions.md` — repo rules for GitHub Copilot / agents

Describe it as *"reference implementation, pending shakeout"* until
`SHAKEDOWN.md` is complete.

## Quick start

```bash
cd starter-pack
python -m pip install -r requirements.txt
python verify_package.py       # offline self-check, no auth needed

cp .env.template .env          # fill in TENANT_ID, CLIENT_ID, ENVIRONMENT_ID, BOT_ID

python evaluate.py --list-test-sets sample-agent   # prove auth + IDs work
python evaluate.py --suite smoke --no-persist      # first real run
python evaluate.py                                 # full matrix
```

In VS Code, these are also available as tasks
(**Terminal → Run Task**, or `Ctrl/Cmd+Shift+P` → *Run Task*).

Full walkthrough: **[SETUP.md](SETUP.md)**.

### Tests

The gate, result parsing, config validation and reporters have an offline
unit suite (no auth, no tenant). Run it before trusting a change to any of them:

```bash
cd starter-pack
python -m pip install -r requirements-dev.txt
python -m pytest
```

These lock in the fail-safe gate behaviour described in
`.github/PROVENANCE.md` — a run with no gradeable results, or an unclassifiable
status token, must never pass.

---

## What the runner does

```
config/agents.json
      |
      v
  plan: agents x suites x personas
      |
      v
  resolve test set by displayName  ->  GET  /makerevaluation/testsets
      |
      v
  start run (one per persona)      ->  POST /makerevaluation/testsets/{id}/run
      |                                      body: { "mcsConnectionId": ... }
      v
  poll until terminal              ->  GET  /makerevaluation/testruns/{runId}
      |
      +--> flatten to one record per test case x test method
      +--> persist to Dataverse (survives the 89-day platform retention)
      +--> JSON + JUnit XML output
      +--> quality gate -> exit code
```

Exit codes: `0` pass · `1` gate failed · `2` config/auth error · `3` required run errored.

---

## Five design decisions worth knowing

**1. Runs execute in parallel.**
The portal runs one test set at a time. The API does not have that limitation,
so a four-persona security matrix finishes in the time of its slowest single
run instead of four runs back to back.

**2. Thresholds are per test method — never blended.**
*Compare meaning* answers "did it say the right thing". *General quality*
answers "how well did it say it". A blended 60% could be accurate-but-rambling
or polished-but-wrong. The gate scores each independently.

**3. `Invalid` is not `fail`.**
An Invalid result means the test case had no expected answer or keywords — a
suite defect, not an agent regression. Invalid results are excluded from pass
rates and tracked separately, with their own threshold.

**4. Persistence is at the metric grain.**
One row per test case × test method, not one per run. That grain is what makes
"which method is failing, for which persona, since which agent version, and
why" answerable a year later.

**5. Unrecognised values are surfaced AND they block the gate.**
The API's status tokens and run states are not exhaustively documented. The
runner normalises what it knows, treats unknown run states as terminal, and
prints anything it does not recognise instead of silently scoring it. Crucially,
unclassifiable results also **fail the gate** (`failOnUnknownStatus`) — an
earlier version surfaced them but let them pass, which meant the first run
against a real tenant, when unmapped tokens are most likely, could green-light
a release with nothing actually verified. A gate cannot pass on absent
evidence: `minScoredResults` enforces that too.

**6. `runOnPublishedBot` is always sent explicitly.**
Found in the connector manifest, absent from the REST API documentation. A gate
that evaluates the *draft* agent while you believe it tested the *published*
one passes, promotes, and leaves production behaving differently from what was
measured. The runner never inherits the platform default.

---

## Why there is no pre-built solution .zip

The most-requested artifact is a `.zip` to import. It would be the wrong thing
to ship, for one concrete reason:

> A table's customisation prefix comes from the solution publisher and
> **cannot be changed after the table is created.**

A pre-baked solution would permanently stamp someone else's prefix into your
environment. `dataverse/provision_schema.py` takes the prefix as an argument,
so you own your naming from the first run — and once the tables exist you
export a real, environment-native, versioned solution:

```bash
pac solution export --name CopilotStudioEvaluationFramework --managed false
```

That exported solution is a better ALM artifact than anything shippable here:
it carries your prefix, your publisher, and your version history.

The same logic applies to Power BI — see `powerbi/README.md`.

---

## Layout

```
starter-pack/
├── evaluate.py              entry point
├── eval_runner/
│   ├── auth.py              token acquisition (4 modes)
│   ├── config.py            typed config loading + validation
│   ├── pp_client.py         Power Platform API client + result parsing
│   ├── runner.py            parallel agent x suite x persona orchestration
│   ├── gate.py              threshold evaluation
│   ├── dataverse.py         results persistence ($batch)
│   └── reporters.py         console, JSON, JUnit XML
├── config/agents.json       agents, suites, personas, thresholds
├── dataverse/
│   ├── schema.json          table + column + relationship definitions
│   └── provision_schema.py  idempotent provisioner (--dry-run supported)
├── testsets/*.csv           seed test sets, import-ready
├── workflows/               GitHub Actions templates
├── azure/                   Azure DevOps pipeline + Azure guidance
├── powerbi/                 M queries + DAX measures
├── samples/                 captured real API responses (populated during shakeout)
├── verify_package.py        offline self-check
├── tests/                   pytest unit suite (gate, parsing, config, reporters)
├── .vscode/tasks.json       shakeout steps as VS Code tasks
├── .github/
│   ├── copilot-instructions.md   repo rules for GitHub Copilot
│   └── PROVENANCE.md             verified vs unverified, in detail
├── AGENTS.md                same rules, for agents that read AGENTS.md
├── SHAKEDOWN.md             the verification runbook
└── SETUP.md                 full walkthrough
```

---

## Requirements

- Python 3.9+
- `requests` (required), `msal` (delegated auth only)
- A Copilot Studio agent on the standard harness with at least one test set
- An Entra app registration with access to the Power Platform API

---

## Source documentation

- [About agent evaluation](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-intro)
- [Automate agent evaluations with Power Platform API](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-rest-api)
- [Trigger agent evaluations with connectors](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-automate-tools)
- [Choose evaluation methods](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-overview)
- [Create a single response test set](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-create)
- [Power Platform API authentication](https://learn.microsoft.com/en-us/power-platform/admin/programmability-authentication-v2)
- [Create and update table definitions using the Web API](https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/create-update-entity-definitions-using-web-api)
- [GitHub Actions for Microsoft Power Platform](https://learn.microsoft.com/en-us/power-platform/alm/devops-github-actions)

---

## Status

Agent evaluation is a **preview** capability. The runner is written defensively
around the parts of the API surface that are not exhaustively documented, but
re-check the Learn articles above before committing to an implementation date.
