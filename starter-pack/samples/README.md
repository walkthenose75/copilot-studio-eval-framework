# Captured API responses

Real, unmodified responses from the Power Platform API, captured during the
shakeout (see `SHAKEDOWN.md`).

These are the ground truth for the response-shape questions the documentation
does not answer: exact field names, nesting, status token values and run state
values.

| File | Source |
|---|---|
| `01-testsets.json` | `GET .../makerevaluation/testsets` |
| `02-testruns-list.json` | `GET .../makerevaluation/testruns` |
| `03-testrun-detail.json` | `GET .../makerevaluation/testruns/{runId}` |

**Scrub before committing.** Real responses can contain agent answers drawn
from knowledge sources, which may include customer or business data. Review
each file and redact before it goes into a shared repo.
