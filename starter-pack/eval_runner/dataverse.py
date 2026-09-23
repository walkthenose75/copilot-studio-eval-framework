"""Persist evaluation results to Dataverse.

Why this exists: Copilot Studio retains evaluation results for 89 days.
Anything you need for year-over-year trend, audit evidence or cross-agent
scorecards has to be written somewhere durable at run time.

Grain: one row per test case x test method. Storing one row per run instead
makes most of the useful questions unanswerable later.

Uses the Dataverse Web API (/api/data/v9.2). Table and column names are built
from a configurable publisher prefix so this works in any environment.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from .auth import TokenProvider

API_PATH = "/api/data/v9.2"


class DataverseError(Exception):
    pass


class DataverseSink:
    def __init__(self, org_url: str, token_provider: TokenProvider, prefix: str = "cse") -> None:
        self.org_url = org_url.rstrip("/")
        self._tokens = token_provider
        self.prefix = prefix.strip().strip("_")
        self._session = requests.Session()

    # -- naming ---------------------------------------------------------

    def table(self, name: str) -> str:
        """Entity set name (plural) for a logical table."""
        return f"{self.prefix}_{name}s"

    def col(self, name: str) -> str:
        return f"{self.prefix}_{name}"

    # -- plumbing -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            **self._tokens.header(),
        }

    def create(self, entity_set: str, record: dict[str, Any]) -> str:
        """POST a record; returns its GUID (parsed from OData-EntityId)."""
        url = f"{self.org_url}{API_PATH}/{entity_set}"
        headers = {**self._headers(), "Prefer": "return=representation"}
        response = self._session.post(url, json=record, headers=headers, timeout=120)
        if not response.ok:
            raise DataverseError(
                f"POST {entity_set} failed ({response.status_code}): {response.text[:600]}"
            )
        if response.content:
            try:
                payload = response.json()
                for key, value in payload.items():
                    if key.endswith("id") and isinstance(value, str) and len(value) == 36:
                        return value
            except ValueError:
                pass
        entity_id = response.headers.get("OData-EntityId", "")
        return entity_id.split("(")[-1].rstrip(")") if "(" in entity_id else ""

    def create_batch(self, entity_set: str, records: list[dict[str, Any]], chunk: int = 100) -> int:
        """Insert many rows using OData $batch. Returns the count written."""
        written = 0
        for start in range(0, len(records), chunk):
            block = records[start:start + chunk]
            written += self._batch_block(entity_set, block)
        return written

    def _batch_block(self, entity_set: str, records: list[dict[str, Any]]) -> int:
        boundary = "batch_cse_eval"
        changeset = "changeset_cse_eval"
        lines: list[str] = [f"--{boundary}",
                            f"Content-Type: multipart/mixed; boundary={changeset}", ""]
        for index, record in enumerate(records, start=1):
            body = json.dumps(record, default=str)
            lines += [
                f"--{changeset}",
                "Content-Type: application/http",
                "Content-Transfer-Encoding: binary",
                f"Content-ID: {index}",
                "",
                f"POST {self.org_url}{API_PATH}/{entity_set} HTTP/1.1",
                "Content-Type: application/json;type=entry",
                "",
                body,
                "",
            ]
        lines += [f"--{changeset}--", f"--{boundary}--", ""]
        payload = "\r\n".join(lines)

        headers = {
            **self._tokens.header(),
            "Content-Type": f"multipart/mixed; boundary={boundary}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        }
        response = self._session.post(
            f"{self.org_url}{API_PATH}/$batch",
            data=payload.encode("utf-8"),
            headers=headers,
            timeout=300,
        )
        if not response.ok:
            raise DataverseError(
                f"$batch into {entity_set} failed ({response.status_code}): {response.text[:600]}"
            )
        if "HTTP/1.1 4" in response.text or "HTTP/1.1 5" in response.text:
            raise DataverseError(
                f"$batch into {entity_set} reported per-item errors: {response.text[:800]}"
            )
        return len(records)

    # -- domain writes --------------------------------------------------

    def persist_execution(self, execution: dict, context: dict) -> dict:
        """Write one evaluation run plus its metric rows.

        `context` carries the pipeline facts the API cannot know:
        agentKey, agentDisplayName, environmentTier, solutionVersion,
        commitSha, persona, suite, category.
        """
        run = execution.get("raw", {}) or {}
        run_record = {
            self.col("name"): (run.get("name") or execution["label"])[:100],
            self.col("runid"): str(execution.get("runId") or "")[:100],
            self.col("agentkey"): str(context.get("agentKey", ""))[:100],
            self.col("agentname"): str(context.get("agentDisplayName", ""))[:100],
            self.col("botid"): str(run.get("cdsBotId") or context.get("botId", ""))[:100],
            self.col("environmentid"): str(run.get("environmentId") or context.get("environmentId", ""))[:100],
            self.col("environmenttier"): str(context.get("environmentTier", ""))[:50],
            self.col("solutionversion"): str(context.get("solutionVersion", ""))[:50],
            self.col("commitsha"): str(context.get("commitSha", ""))[:50],
            self.col("persona"): str(context.get("persona", ""))[:100],
            self.col("suite"): str(context.get("suite", ""))[:100],
            self.col("category"): str(context.get("category", ""))[:50],
            self.col("testsetid"): str(run.get("testSetId") or "")[:100],
            self.col("testsetname"): str(context.get("testSetName", ""))[:100],
            self.col("mcsconnectionid"): str(run.get("mcsConnectionId") or "")[:100],
            self.col("ownerid"): str(run.get("ownerId") or "")[:100],
            self.col("state"): str(run.get("state") or "")[:50],
            self.col("totaltestcases"): _as_int(run.get("totalTestCases")),
            self.col("passcount"): execution["summary"]["totals"]["pass"],
            self.col("failcount"): execution["summary"]["totals"]["fail"],
            self.col("invalidcount"): execution["summary"]["totals"]["invalid"],
            self.col("passrate"): _as_decimal(execution["summary"]["totals"].get("passRate")),
        }
        if run.get("startTime"):
            run_record[self.col("starttime")] = run["startTime"]
        if run.get("endTime"):
            run_record[self.col("endtime")] = run["endTime"]

        run_record = {k: v for k, v in run_record.items() if v not in (None, "")}
        run_guid = self.create(self.table("evaluationrun"), run_record)

        metric_rows = []
        for record in execution.get("records", []):
            row = {
                self.col("name"): f"{record.get('testCaseId', '')}-{record.get('method', '')}"[:100],
                self.col("testcaseid"): str(record.get("testCaseId") or "")[:100],
                self.col("method"): str(record.get("method") or "")[:100],
                self.col("outcome"): record["outcome"][:50],
                self.col("rawstatus"): str(record.get("rawStatus") or "")[:100],
                self.col("airesultreason"): _clip(record.get("aiResultReason"), 4000),
                self.col("errorreason"): _clip(record.get("errorReason"), 2000),
                self.col("persona"): str(context.get("persona", ""))[:100],
                self.col("suite"): str(context.get("suite", ""))[:100],
            }
            score = _as_decimal(record.get("score"))
            if score is not None:
                row[self.col("score")] = score
            if run_guid:
                row[f"{self.col('EvaluationRunId')}@odata.bind"] = (
                    f"/{self.table('evaluationrun')}({run_guid})"
                )
            metric_rows.append({k: v for k, v in row.items() if v not in (None, "")})

        written = self.create_batch(self.table("metricresult"), metric_rows) if metric_rows else 0
        return {"runGuid": run_guid, "metricRowsWritten": written}


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_decimal(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _clip(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit] if text else None


def sink_from_env(token_provider: TokenProvider | None = None) -> DataverseSink | None:
    """Build a sink from DATAVERSE_URL / DATAVERSE_PREFIX, or None if not configured."""
    org_url = os.environ.get("DATAVERSE_URL")
    if not org_url:
        return None
    if token_provider is None:
        from .auth import TokenProvider as TP
        tenant = os.environ.get("TENANT_ID")
        if not tenant:
            raise DataverseError("DATAVERSE_URL is set but TENANT_ID is not.")
        token_provider = TP(
            mode=os.environ.get("DATAVERSE_AUTH_MODE")
            or ("client_secret" if os.environ.get("CLIENT_SECRET") else "device_code"),
            tenant_id=tenant,
            client_id=os.environ.get("CLIENT_ID"),
            client_secret=os.environ.get("CLIENT_SECRET"),
            scope=f"{org_url.rstrip('/')}/.default",
            resource=org_url.rstrip("/"),
        )
    return DataverseSink(
        org_url=org_url,
        token_provider=token_provider,
        prefix=os.environ.get("DATAVERSE_PREFIX", "cse"),
    )
