"""Typed client for the Copilot Studio agent-evaluation operations of the
Power Platform API.

Every endpoint below is documented at:
  https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-rest-api

  GET  /copilotstudio/environments/{env}/bots/{bot}/api/makerevaluation/testsets
  GET  /copilotstudio/environments/{env}/bots/{bot}/api/makerevaluation/testsets/{testSetId}
  POST /copilotstudio/environments/{env}/bots/{bot}/api/makerevaluation/testsets/{testSetId}/run
  GET  /copilotstudio/environments/{env}/bots/{bot}/api/makerevaluation/testruns
  GET  /copilotstudio/environments/{env}/bots/{bot}/api/makerevaluation/testruns/{runId}

All take ?api-version=2024-10-01.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

import requests

from .auth import TokenProvider

# The docs describe run progress via `state` / `executionState` but do not
# publish an exhaustive list of values. We therefore treat "still going" as a
# closed set and everything else as terminal - which fails safe: an unexpected
# value ends the poll rather than looping until timeout.
NON_TERMINAL_STATES = {"queued", "running", "inprogress", "in_progress", "notstarted", "pending"}

# Result status tokens are likewise not exhaustively published. We normalise
# case and keep anything unrecognised visible instead of silently scoring it.
PASS_TOKENS = {"passed", "pass", "succeeded", "success", "true"}
FAIL_TOKENS = {"failed", "fail", "false"}
INVALID_TOKENS = {"invalid", "notapplicable", "na", "none", "skipped"}


class ApiError(Exception):
    """Raised when the Power Platform API returns an unexpected response."""

    def __init__(self, message: str, status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class EvaluationClient:
    def __init__(
        self,
        token_provider: TokenProvider,
        environment_id: str,
        bot_id: str,
        base_url: str = "https://api.powerplatform.com",
        api_version: str = "2024-10-01",
        timeout: int = 120,
    ) -> None:
        self._tokens = token_provider
        self.environment_id = environment_id
        self.bot_id = bot_id
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.timeout = timeout
        self._session = requests.Session()

    # -- plumbing -------------------------------------------------------

    def _url(self, suffix: str) -> str:
        return (
            f"{self.base_url}/copilotstudio/environments/{self.environment_id}"
            f"/bots/{self.bot_id}/api/makerevaluation/{suffix}"
        )

    def _request(self, method: str, suffix: str, body: dict | None = None) -> Any:
        url = self._url(suffix)
        headers = {"Accept": "application/json", **self._tokens.header()}
        if body is not None:
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(4):
            response = self._session.request(
                method,
                url,
                params={"api-version": self.api_version},
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
            # Transient: honour Retry-After when present.
            if response.status_code in (429, 500, 502, 503, 504):
                delay = float(response.headers.get("Retry-After", 2 ** attempt))
                last_error = ApiError(
                    f"{method} {suffix} returned {response.status_code}",
                    response.status_code,
                    response.text[:500],
                )
                time.sleep(min(delay, 30))
                continue
            if response.status_code in (401, 403):
                raise ApiError(
                    f"{method} {suffix} returned {response.status_code}. "
                    "For a service principal, confirm a Power Platform RBAC role is "
                    "assigned to it - the Power Platform API grants delegated "
                    "permissions only, so app permissions alone are not enough.",
                    response.status_code,
                    response.text[:500],
                )
            if not response.ok:
                raise ApiError(
                    f"{method} {suffix} returned {response.status_code}.",
                    response.status_code,
                    response.text[:800],
                )
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise ApiError(
                    f"{method} {suffix} returned non-JSON content.",
                    response.status_code,
                    response.text[:300],
                ) from exc
        raise last_error or ApiError(f"{method} {suffix} failed after retries.")

    # -- operations -----------------------------------------------------

    def list_test_sets(self) -> list[dict]:
        payload = self._request("GET", "testsets")
        return payload.get("value", []) if isinstance(payload, dict) else list(payload)

    def get_test_set(self, test_set_id: str) -> dict:
        return self._request("GET", f"testsets/{test_set_id}")

    def resolve_test_set_id(self, display_name: str) -> str:
        """Resolve a test set by display name, requiring state == Active.

        A usable test set has the status Active (documented).
        """
        candidates = self.list_test_sets()
        exact = [t for t in candidates if (t.get("displayName") or "").strip() == display_name.strip()]
        if not exact:
            available = ", ".join(sorted(f"{t.get('displayName')}" for t in candidates)) or "(none)"
            raise ApiError(
                f"No test set named '{display_name}' on this agent. Available: {available}"
            )
        active = [t for t in exact if str(t.get("state", "")).lower() == "active"]
        chosen = (active or exact)[0]
        if not active:
            print(
                f"  ! Test set '{display_name}' has state "
                f"'{chosen.get('state')}' (expected 'Active').",
                flush=True,
            )
        return chosen["id"]

    def start_run(
        self,
        test_set_id: str,
        mcs_connection_id: str | None = None,
        run_on_published_bot: bool | None = None,
        evaluation_run_name: str | None = None,
    ) -> str:
        """POST .../testsets/{id}/run - returns the runId.

        Body parameters, as published in the Microsoft Copilot Studio connector
        manifest for RunAgentMakerEvaluationTestSet:

          mcsConnectionId     optional - user profile for the run.
                              "leave empty for anonymous run"
          runOnPublishedBot   optional - "Whether to run on the published bot
                              or on draft version"
          evaluationRunName   optional - name for the evaluation run

        ALWAYS send runOnPublishedBot explicitly for a release gate. The
        platform default is not documented, and a gate that silently evaluates
        the DRAFT agent while you believe it tested the PUBLISHED one is the
        worst failure mode available: it passes, you promote, and production
        behaves differently from what was measured.
        """
        body: dict[str, Any] = {}
        if mcs_connection_id:
            body["mcsConnectionId"] = mcs_connection_id
        if run_on_published_bot is not None:
            body["runOnPublishedBot"] = bool(run_on_published_bot)
        if evaluation_run_name:
            body["evaluationRunName"] = evaluation_run_name[:100]
        payload = self._request("POST", f"testsets/{test_set_id}/run", body=body)
        run_id = payload.get("runId") or payload.get("id")
        if not run_id:
            raise ApiError(f"Run started but no runId was returned. Payload: {payload}")
        return run_id

    def get_run(self, run_id: str) -> dict:
        return self._request("GET", f"testruns/{run_id}")

    def list_runs(self) -> list[dict]:
        payload = self._request("GET", "testruns")
        return payload.get("value", []) if isinstance(payload, dict) else list(payload)

    def poll_run(
        self,
        run_id: str,
        interval_sec: int = 10,
        timeout_sec: int = 1800,
        on_progress=None,
    ) -> dict:
        """Poll until the run reaches a terminal state or the timeout expires."""
        deadline = time.time() + timeout_sec
        run: dict = {}
        while time.time() < deadline:
            run = self.get_run(run_id)
            state = str(run.get("state") or run.get("executionState") or "").strip()
            if on_progress:
                on_progress(run)
            if state.lower().replace(" ", "") not in NON_TERMINAL_STATES:
                return run
            time.sleep(interval_sec)
        raise ApiError(
            f"Run {run_id} did not reach a terminal state within {timeout_sec}s "
            f"(last state: {run.get('state')})."
        )


# -- result parsing -----------------------------------------------------

def classify(status: Any) -> str:
    """Map a raw status token to pass / fail / invalid / unknown."""
    token = str(status).strip().lower()
    if token in PASS_TOKENS:
        return "pass"
    if token in FAIL_TOKENS:
        return "fail"
    if token in INVALID_TOKENS or token in ("", "none"):
        return "invalid"
    return "unknown"


def iter_metrics(run: dict) -> Iterable[dict]:
    """Yield one flat record per test case x test method.

    The documented shape is:
        run.testCasesResults[].metricsResults[].result.{status, errorReason,
        aiResultReason, data, ...}

    Field placement has been observed to vary, so each field is read from
    `result`, then `result.data`, then the metric itself. The raw status token
    is always carried through so unexpected values stay visible.
    """
    for case in run.get("testCasesResults", []) or []:
        case_id = case.get("testCaseId")
        case_state = case.get("state")
        for metric in case.get("metricsResults", []) or []:
            result = metric.get("result") or {}
            data = result.get("data") if isinstance(result.get("data"), dict) else {}

            def pick(key: str):
                for source in (result, data, metric):
                    if isinstance(source, dict) and source.get(key) is not None:
                        return source.get(key)
                return None

            raw_status = pick("status")
            yield {
                "testCaseId": case_id,
                "testCaseState": case_state,
                "method": metric.get("type") or metric.get("metricType"),
                "rawStatus": raw_status,
                "outcome": classify(raw_status),
                "score": pick("score"),
                "aiResultReason": pick("aiResultReason"),
                "errorReason": pick("errorReason"),
                "relevance": pick("relevance"),
                "groundedness": pick("groundedness"),
                "completeness": pick("completeness"),
                "abstention": pick("abstention"),
            }


def summarize(records: list[dict]) -> dict:
    """Aggregate flat metric records into per-method and overall counts."""
    by_method: dict[str, dict[str, int]] = {}
    totals = {"pass": 0, "fail": 0, "invalid": 0, "unknown": 0}
    for record in records:
        method = record.get("method") or "(unknown method)"
        bucket = by_method.setdefault(method, {"pass": 0, "fail": 0, "invalid": 0, "unknown": 0})
        bucket[record["outcome"]] += 1
        totals[record["outcome"]] += 1

    def rate(bucket: dict[str, int]) -> float | None:
        scored = bucket["pass"] + bucket["fail"]
        return (bucket["pass"] / scored) if scored else None

    return {
        "byMethod": {m: {**b, "passRate": rate(b)} for m, b in by_method.items()},
        "totals": {**totals, "passRate": rate(totals)},
        "metricCount": len(records),
    }
