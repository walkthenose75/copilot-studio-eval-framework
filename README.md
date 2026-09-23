# Enterprise Evaluation Framework for Copilot Studio Agents

An interactive, single-page briefing on building an enterprise-scale evaluation practice for
Microsoft Copilot Studio agents — standardized test sets, automated grading, CI/CD quality gates,
a durable results repository, and cross-agent governance reporting.

**Repository:** `walkthenose75/copilot-studio-eval-framework` (public)

**Live briefing:** https://walkthenose75.github.io/copilot-studio-eval-framework/
— served by GitHub Pages from `main` → `/docs`. See `PUBLISH.md` to (re)publish.

## Scope

- Built for agents powered by the Copilot Studio **standard harness** — the runtime where agent
  evaluation is automatable today: multi-method test sets, four safety evaluators, and the
  **Power Platform REST API** and connector actions this framework is built on are all documented for
  the standard harness. The new agent experience (**GitHub Copilot harness**) has its own *Evaluate*
  tab, but as of September 2026 it is a preview limited to a single method (*General quality*, which
  doesn't compare to expected answers) and documents no evaluation REST API, so automated release
  gates aren't possible there yet. The framework's logic is response-level, so it carries over
  unchanged as that experience reaches parity. See
  [Harnesses in Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview),
  [About agent evaluation (standard harness)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-intro),
  and [Evaluate an agent (preview)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/analytics-agent-evaluation-intro).
- Capability status is marked inline throughout: **GA**, **Preview**, or **Customer-built**
  (a pattern assembled from supported building blocks).
- Every product behaviour described is sourced from public Microsoft documentation. The full source
  list is in the Appendix section of the page.

## Contents

| # | Section |
|---|---|
| 01 | Executive summary |
| 02 | Why agent evaluation matters |
| 03 | Enterprise requirements, mapped to capability |
| 04 | Evaluation maturity model |
| 05 | Native Copilot Studio evaluation capability |
| 06 | Evaluation taxonomy — six categories |
| 07 | Identity-aware (persona) evaluation |
| 08 | Evaluation automation architecture |
| 09 | CI/CD integration — REST API and connector |
| 10 | Managing test assets |
| 11 | Evaluation data model |
| 12 | Power BI governance reporting |
| 13 | Operating model |
| 14 | Recommended five-phase approach |
| 15 | Open architecture decisions |
| 16 | Next steps |
| SP | Starter pack — working implementation |
| A | Appendix — limits and full source list |

## Starter pack

`starter-pack/` is a working implementation of the build layer — not pseudocode.

| Component | What it does |
|---|---|
| `evaluate.py` + `eval_runner/` | Runs the agent × suite × persona matrix against the documented `makerevaluation` API, in parallel, with polling, gating and pipeline exit codes |
| `dataverse/` | Schema + idempotent provisioner for the results repository (survives the 89-day platform retention) |
| `workflows/` | GitHub Actions release gate and scheduled drift detection |
| `azure/` | Azure DevOps pipeline equivalent, plus what Azure is actually needed for |
| `powerbi/` | Power Query M + 25 DAX measures for the three governance report pages |
| `testsets/` | Seed CSVs in the documented import format |

Start with [`starter-pack/SETUP.md`](starter-pack/SETUP.md). First command to run:

```bash
python evaluate.py --list-test-sets sample-agent
```

Two things to know going in:

- **The Power Platform API grants delegated permissions only.** A service
  principal gets a token and still receives 401/403 until a Power Platform RBAC
  role is assigned to it. Prove the pipeline with device-code auth first.
- **There is no pre-built solution `.zip`, deliberately.** A table's
  customisation prefix comes from the publisher and cannot be changed after
  creation, so a pre-baked solution would stamp someone else's prefix into your
  environment permanently. The provisioner takes your prefix as an argument;
  you then export a real, environment-native solution with `pac solution export`.

## Repository layout

```
docs/
  index.html           self-contained page — no build step, no dependencies
  .nojekyll            serve files as-is
starter-pack/
  evaluate.py          entry point
  eval_runner/         auth, API client, orchestration, gate, persistence
  config/agents.json   agents, suites, personas, thresholds
  dataverse/           schema + provisioning script
  testsets/            seed CSVs
  workflows/           GitHub Actions templates
  azure/               Azure DevOps pipeline
  powerbi/             M queries + DAX measures
  SETUP.md             full walkthrough
README.md
PUBLISH.md
LICENSE
```

## Publishing

This is a **public** repository. Run `INIT-REPO.ps1` (Windows) or `INIT-REPO.sh`
to create it at `walkthenose75`, push, and enable GitHub Pages in one step.

The briefing is then live at
`https://walkthenose75.github.io/copilot-studio-eval-framework/`, served from
`main` → `/docs`. `docs/index.html` is fully self-contained, so it also works
sent as a file. See `PUBLISH.md` for details and manual steps.

## Editing

`docs/index.html` is a single self-contained file: markup, CSS and a small amount of vanilla
JavaScript (scroll-spy navigation, reading progress, light/dark toggle, copy buttons). There is no
framework, no build tooling and no external runtime dependency. Edit and commit.

## Disclaimer

This is a personal project. **It is not an official Microsoft product**, is not
supported by Microsoft, and does not represent Microsoft's official guidance.
Views and content here are the author's own.

Everything describing Microsoft Copilot Studio behaviour is sourced from
Microsoft's public documentation, linked inline and listed in the briefing's
appendix. Microsoft, Copilot Studio, Power Platform, Dataverse, Power BI and
Azure are trademarks of the Microsoft group of companies.

**Agent evaluation is a preview capability** and its documentation changes as
the feature matures. Re-check the linked Microsoft Learn articles before
relying on any specific behaviour described here.

### On the starter pack specifically

The code in `starter-pack/` is a **reference implementation**. Request shapes
are verified against Microsoft's published Copilot Studio connector definition;
response handling is written defensively but **has not been verified against a
live tenant**. See `starter-pack/.github/PROVENANCE.md` for exactly what is and
is not verified, and `starter-pack/SHAKEDOWN.md` for the runbook that closes
the gap.

Do not wire this into a production release gate before completing that
shakeout. A quality gate you have not validated is worse than no gate, because
it manufactures false confidence.

## License

[MIT](LICENSE) — Copyright (c) 2026 Kyle Thompson.

Provided "as is", without warranty of any kind. See `LICENSE` for the full
text.
