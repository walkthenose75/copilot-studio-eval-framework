# Repo instructions for GitHub Copilot

You are working on the **Copilot Studio Enterprise Evaluation Framework** — a
runner, Dataverse results repository, CI/CD gate and Power BI layer for
automated evaluation of Microsoft Copilot Studio agents.

## Read this first

This code is **written against documentation but never executed against the
live Power Platform API.** Request shapes are verified against the Microsoft
Copilot Studio connector manifest. **Response shapes are not verified.**

Your primary job is the shakeout in `SHAKEDOWN.md`: run each step against a
real tenant, compare actual behaviour to what the code assumes, and correct
the code. Work through it in order — each step gates the next.

## Non-negotiable rules

1. **Never invent API behaviour.** If you need to know what a field contains,
   call the API and look. Do not "fix" a parsing bug by guessing a new field
   name — capture a real response, save it to `samples/`, then code to it.
2. **Never widen a gate to make it pass.** If the gate fails, the finding is
   real. Fix the agent or the test set, not the threshold.
3. **Preserve the fail-safe posture.** Unknown run states are treated as
   terminal; unrecognised status tokens are surfaced as `unknown`, never
   silently scored as pass. Keep it that way.
4. **`runOnPublishedBot` is always sent explicitly.** Never let it default.
   A gate that evaluates the draft while reporting on the published agent is
   the worst failure mode in this system.
5. **Do not commit secrets.** `.env` is git-ignored. Connection IDs, client
   secrets and org URLs never go in tracked files.
6. **Ask before destructive Dataverse operations.** Table creation is fine;
   deletion is not.

## Architecture

```
evaluate.py            CLI entry point; orchestrates and sets the exit code
eval_runner/
  auth.py              token acquisition - 4 modes
  config.py            typed config from config/agents.json
  pp_client.py         Power Platform API client + response parsing
  runner.py            parallel agent x suite x persona orchestration
  gate.py              threshold evaluation
  dataverse.py         persistence at metric grain, via $batch
  reporters.py         console / JSON / JUnit XML
dataverse/             schema.json + idempotent provisioner
config/agents.json     agents, suites, personas, thresholds - data, not code
testsets/              seed CSVs for import into Copilot Studio
workflows/             GitHub Actions templates (copy to .github/workflows/)
powerbi/               Power Query M + DAX
```

Exit codes: `0` pass · `1` gate failed · `2` config/auth error · `3` required
run errored.

## Verified vs unverified — keep this current

| Area | State |
|---|---|
| Request shapes (paths, verbs, body params) | Verified against connector manifest |
| `mcsConnectionId`, `runOnPublishedBot`, `evaluationRunName` | Verified as body params |
| Control flow, parsing, gating, reporters | Tested against a local mock |
| **Response field names and nesting** | **UNVERIFIED** |
| **Status tokens** (`PASS_TOKENS` etc. in `pp_client.py`) | **GUESSED — expect to fix** |
| **Run state values** (`NON_TERMINAL_STATES`) | **GUESSED** |
| **Dataverse `@odata.bind` lookup casing** | **UNVERIFIED — known failure area** |
| **Power BI M + DAX** | **Never executed** |

Update this table as you verify things. It is the honest status of the project.

## Style

- Python 3.9+, standard library plus `requests` (and `msal` for delegated auth).
  Do not add dependencies without asking.
- Type hints on public functions. Comments explain *why*, not *what*.
- Keep config data-driven: adding an agent or persona must not require a code
  change.
