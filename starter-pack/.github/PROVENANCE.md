# Provenance — what is verified, and how

Read this before describing this repository's status to anyone.

## Three tiers of confidence

### Tier 1 — Verified against Microsoft's published connector definition

Pulled from the live **Microsoft Copilot Studio** connector manifest
(`shared_microsoftcopilotstudio`, Standard tier, publisher Microsoft), not from
documentation prose:

| Verified | Detail |
|---|---|
| Five evaluation operations exist | `GetAgentMakerEvaluationTestSets`, `GetAgentMakerEvaluationTestSetDetails`, `RunAgentMakerEvaluationTestRun`* , `GetAgentMakerEvaluationTestRuns`, `GetAgentMakerEvaluationTestRunDetails` |
| Trigger is **POST** | `POST .../makerevaluation/testsets/{TestSetId}/run` — confirms the docs' POST, contradicts community reports of GET |
| Path structure | `/api/makerevaluation/testsets` and `/api/makerevaluation/testruns` |
| `mcsConnectionId` | Body parameter, optional — *"leave empty for anonymous run"* |
| `runOnPublishedBot` | Body parameter, optional — *"Whether to run on the published bot or on draft version"* |
| `evaluationRunName` | Body parameter, optional |

\* run operation id is `RunAgentMakerEvaluationTestSet`.

**`runOnPublishedBot` was found this way, not from the documentation.** It is
absent from the Learn REST API article. Without it a release gate may evaluate
the *draft* agent while reporting on the published one. The runner now always
sends it explicitly.

### Tier 2 — Tested, but against a self-authored mock

The runner was executed end to end against a mock server written from the same
documentation the client was written from. This proves **internal
consistency**, not external correctness:

- Parallel orchestration, polling loop, retry and timeout handling
- Result flattening and aggregation arithmetic
- Gate logic, including both exit paths (0 and 1)
- JUnit XML well-formedness, JSON structure
- Dataverse payload construction and `$batch` envelope assembly

**The limitation is circular:** if the documentation was misread, the mock
encodes the identical misreading and the test passes green.

### Tier 3 — Not verified at all

| Unverified | Risk |
|---|---|
| Every response field name and nesting level | Parser may read nulls |
| Status tokens (`PASS_TOKENS` etc.) | **Invented.** Expect first-run corrections |
| Run state values (`NON_TERMINAL_STATES`) | Guessed; unknown states fail safe as terminal |
| Presence of a `score` field | Assumed |
| Live Dataverse table creation | Dry-run only — never POSTed |
| `@odata.bind` lookup casing | Dataverse OData is case-sensitive on navigation properties; Web-API-created lookups are a documented failure source |
| `$batch` insert behaviour | Mock accepted it without validating |
| Power Query M | Never executed. Connector function name is build-dependent |
| All 25 DAX measures | Never evaluated by any engine |
| GitHub Actions / Azure Pipelines | Parse as valid YAML; never run on a real runner |
| All four auth modes | No real token was ever acquired |

## Also checked

- CSV seeds conform to the documented import format: exact headers
  `Question,Expected response`, ≤100 questions, ≤1,000 characters per question
- Dataverse schema columns reconcile 1:1 with what `dataverse.py` writes
  (32 columns, 2 tables)
- Workflow and pipeline YAML parse cleanly

## Adversarial review — 2026-09-19

The package was reviewed by executing it against hostile inputs rather than
re-reading it. Six defects were found and fixed. The most serious were real
and would have caused silent failures in production use.

### D1 (critical) — the quality gate could pass with no evidence

Four distinct ways the gate returned PASS when it must not:

| Scenario | Old behaviour |
|---|---|
| Run produced zero results | **PASS** |
| Every result unclassifiable (`unknown`) | **PASS** |
| Safety evaluators unclassifiable, functional tests green | **PASS** |
| Hard-stop method (e.g. ContentSafety) never ran at all | **PASS**, with a footnote |

The third is the dangerous one: a release promoted with safety never
evaluated. And it was *most likely to occur on the first real run*, because
unmapped status tokens are expected then — exactly when the gate is trusted
least and relied on most.

This directly contradicted the "fails safe" claim previously made in this
file and in the README. Unknown results failed **open**, not safe.

**Fixed.** Three new blocking rules:
- `minScoredResults` (default 1) — a gate cannot pass on absent evidence
- `failOnUnknownStatus` (default true) — unclassifiable results block
- A hard-stop method that never produced any result is now a **violation**,
  not a note

Verified: all four scenarios now fail; a healthy run still passes.

### D2 (high) — config errors exited 1 instead of 2

A missing `botId`, a missing `testSetName`, or malformed JSON raised a raw
`KeyError` / `JSONDecodeError` and exited **1**. In CI, exit 1 means *the
quality gate failed* — sending an engineer to debug an agent when the real
fault was a typo in a config file.

**Fixed.** All configuration faults now raise `ConfigError` and exit **2**,
with messages that name the offending agent, suite and property.

### D3 — `runOnPublishedBot` was not being sent

Found earlier via the connector manifest. Absent from the REST API docs; a
gate could evaluate the *draft* agent while reporting on the published one.
Now always sent explicitly.

### D4 — Power BI connector function name

`CommonDataService.Database` vs `Dataverse.Database` is build-dependent
(Sept 2024+). Both queries now route through one `DataverseDb` helper.

### D5 — a `str.replace()` patch silently no-op'd

During this review, an edit targeting the `Thresholds` dataclass was applied
to the wrong module and silently did nothing, because `.replace()` on absent
text is not an error. Caught only because the fix was re-tested rather than
assumed. Every patch in this review was verified by execution afterwards.

### D6 — parser robustness confirmed (no defect)

Nine malformed payload shapes were thrown at `iter_metrics()` — null
collections, missing `result`, `data` as a string instead of an object,
booleans as status. No crashes; all degraded to `invalid` or `unknown`
correctly.

### What this review did NOT do

It did not make a single live API call. Every finding above concerns logic
this code controls. The Tier 3 list still stands untouched — response shapes,
status tokens, `@odata.bind` casing, M and DAX remain unverified until
`SHAKEDOWN.md` is run against a tenant.

## How to describe this

**Accurate:** "Reference implementation. Request shapes verified against the
published connector definition; response handling written defensively and
pending a shakeout in our tenant."

**Not accurate:** "Tested and proven."

Run `SHAKEDOWN.md` to close the gap, then update this file.
