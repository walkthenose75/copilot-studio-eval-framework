# Power BI starter

Three report pages over the Dataverse results repository — executive,
operational and engineering.

## Why there is no .pbix / .pbit here

A packaged Power BI template embeds a connection string and a fixed table
schema. Yours differ (your org URL, your publisher prefix), so a pre-built file
would fail to refresh on first open and give you a broken artifact to debug
instead of a working one. The M queries and DAX below build the same model in
about fifteen minutes, against *your* environment, with nothing hidden.

## Build order

1. **Provision the repository** — `python dataverse/provision_schema.py --url ...`
2. **Run an evaluation** so there is data to model — `python evaluate.py`
3. **New Power BI Desktop file** → create the `OrgUrl` parameter
   (Home → Manage parameters → New: `OrgUrl`, Text, `https://yourorg.crm.dynamics.com`)
4. **Add two queries** from `queries.m` — `EvaluationRun` and `MetricResult`
5. **Add a Date table** (`CALENDARAUTO()` or your own) and mark it as a date table
6. **Create relationships**
   - `EvaluationRun[RunKey]` 1 → * `MetricResult[RunKey]`
   - `Date[Date]` 1 → * `EvaluationRun[Run Date]`
7. **Add the measures** from `measures.dax` into a `Measures` table
8. **Build the three pages** below

If your prefix is not `cse`, find/replace `cse_` in `queries.m` before pasting.

## Page 1 — Executive

| Visual | Field / measure |
|---|---|
| KPI cards | `Agent Health Score`, `Release Readiness`, `Agents Evaluated`, `Personas Covered` |
| Bar chart | `Pass Rate` by `EvaluationRun[Agent]`, sorted ascending (worst first) |
| Table | Agent, `Pass Rate`, `Pass Rate Delta`, `Drift Flag`, `Coverage Status` |
| Card | `Runs Beyond Platform Retention` — what exists only because you kept it |

Conditional formatting: `Release Readiness` red on *Blocked*, amber on
*Ready with risk*, green on *Ready*.

**The most valuable visual on this page** is a list of agents with a blank
`Pass Rate` — agents nobody is testing. Zero coverage is a bigger finding than
a low score.

## Page 2 — Operational

| Visual | Field / measure |
|---|---|
| Line chart | `Pass Rate` by `Date[Date]`, legend `EvaluationRun[Agent]` |
| Matrix | Rows `EvaluationRun[Suite]`, columns `EvaluationRun[Environment]`, values `Pass Rate` |
| Clustered bar | `Metrics Failed` by `MetricResult[Test Method]` |
| Table | Runs where `Run State` is not `Completed` — run reliability, not agent quality |
| Slicers | Agent, Environment, Suite, Persona, Date range |

## Page 3 — Engineering

| Visual | Field / measure |
|---|---|
| Table | `MetricResult[Failure Cluster]` with `Failures In Cluster`, sorted descending |
| Card | `Distinct Failure Clusters` |
| Matrix | Rows `Test Case ID`, columns `Persona`, values `Pass Rate` — persona divergence |
| Card | `Test Cases Diverging By Persona` |
| Detail table | Test Case ID, Test Method, Outcome, Score, AI Result Reason |

### Read the Failure Cluster table first

`AI Result Reason` is the model's own explanation of why a case failed.
Grouped, it collapses dozens of failures into a handful of root causes — and
the top cluster is very often a single instruction-level fix. It is the
highest-yield visual in the whole report, and the one that has no equivalent
in the Copilot Studio UI.

### Reading the persona matrix

- Same test case, **same** outcome across every persona → the question is not
  identity-sensitive. Fine, but it is not a security test.
- Same test case, **different** outcomes → the security model is doing
  something. Confirm it is doing the *right* thing.
- A restricted persona passing where it should fail → investigate immediately.

## Refresh

Dataverse supports scheduled refresh. Set it to run shortly after your
scheduled evaluation window so the report is never more than one cycle stale.
For near-real-time, point a thin DirectQuery page at `MetricResult`; keep the
executive page on import for speed.
