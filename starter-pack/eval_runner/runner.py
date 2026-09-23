"""Orchestrates the evaluation matrix: agents x suites x personas.

Runs are started in parallel and polled independently. The portal runs one
test set at a time; the API does not have that restriction, so a persona
matrix that would take an hour of clicking finishes in the time of its
slowest single run.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .config import Agent, RunnerConfig, Suite
from .pp_client import ApiError, EvaluationClient, iter_metrics, summarize


def _persona_label(name: str) -> str:
    return "no-user-profile" if name == "__default__" else name


def plan_executions(config: RunnerConfig, agent_keys: list[str] | None = None,
                    suite_filter: list[str] | None = None) -> list[dict]:
    """Expand config into a flat list of (agent, suite, persona) work items."""
    plan: list[dict] = []
    keys = agent_keys or list(config.agents)
    for key in keys:
        agent = config.agent(key)
        for suite in agent.suites:
            if suite_filter and suite.name not in suite_filter:
                continue
            for persona_name in suite.personas:
                plan.append({
                    "agent": agent,
                    "suite": suite,
                    "personaName": persona_name,
                    "label": f"{agent.key}/{suite.name}/{_persona_label(persona_name)}",
                })
    return plan


def execute(config: RunnerConfig, token_provider, plan: list[dict],
            verbose: bool = True) -> list[dict]:
    """Run every planned execution, returning one result dict per item."""
    results: list[dict] = []

    def run_one(item: dict) -> dict:
        agent: Agent = item["agent"]
        suite: Suite = item["suite"]
        label = item["label"]
        client = EvaluationClient(
            token_provider=token_provider,
            environment_id=agent.environment_id,
            bot_id=agent.bot_id,
            base_url=config.base_url,
            api_version=config.api_version,
        )
        persona_name = item["personaName"]
        connection_id = (
            None if persona_name == "__default__"
            else config.persona(persona_name).mcs_connection_id
        )

        try:
            test_set_id = client.resolve_test_set_id(suite.test_set_name)
            if verbose:
                print(f"  > {label}: starting test set {test_set_id}", flush=True)
            # Stamp the run so it is traceable from Copilot Studio back to the
            # exact pipeline execution that triggered it.
            commit = os.environ.get("GITHUB_SHA", os.environ.get("BUILD_SOURCEVERSION", ""))
            stamp = commit[:7] if commit else datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
            run_name = f"{label} @ {stamp}"

            run_id = client.start_run(
                test_set_id,
                mcs_connection_id=connection_id,
                run_on_published_bot=agent.run_on_published_bot,
                evaluation_run_name=run_name,
            )
            run = client.poll_run(
                run_id,
                interval_sec=config.poll_interval_sec,
                timeout_sec=config.poll_timeout_sec,
            )
            records = list(iter_metrics(run))
            return {
                "label": label,
                "agentKey": agent.key,
                "agentDisplayName": agent.display_name,
                "environmentId": agent.environment_id,
                "botId": agent.bot_id,
                "suite": suite.name,
                "category": suite.category,
                "testSetName": suite.test_set_name,
                "testSetId": test_set_id,
                "persona": _persona_label(persona_name),
                "required": suite.required,
                "runId": run_id,
                "runName": run_name,
                "runOnPublishedBot": agent.run_on_published_bot,
                "state": run.get("state"),
                "records": records,
                "summary": summarize(records),
                "raw": run,
                "error": None,
            }
        except (ApiError, Exception) as exc:  # noqa: BLE001 - reported, never swallowed
            return {
                "label": label,
                "agentKey": agent.key,
                "agentDisplayName": agent.display_name,
                "environmentId": agent.environment_id,
                "botId": agent.bot_id,
                "suite": suite.name,
                "category": suite.category,
                "testSetName": suite.test_set_name,
                "persona": _persona_label(persona_name),
                "required": suite.required,
                "runId": None,
                "state": "Error",
                "records": [],
                "summary": summarize([]),
                "raw": {},
                "error": f"{type(exc).__name__}: {exc}",
            }

    workers = max(1, min(config.max_parallel_runs, len(plan) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, item): item for item in plan}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if verbose and result["error"]:
                print(f"  ! {result['label']}: {result['error']}", flush=True)

    results.sort(key=lambda r: r["label"])
    return results
