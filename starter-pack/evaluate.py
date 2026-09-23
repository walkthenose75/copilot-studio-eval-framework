#!/usr/bin/env python3
"""Copilot Studio enterprise evaluation runner - entry point.

Typical uses:
    python evaluate.py                          # run everything in config
    python evaluate.py --agent hr-agent         # one agent
    python evaluate.py --suite smoke            # one suite across agents
    python evaluate.py --list-test-sets hr-agent
    python evaluate.py --no-gate                # collect results, never fail

Exit codes (designed for pipelines):
    0  all gates passed
    1  a gate failed
    2  configuration or authentication error
    3  one or more runs errored before producing results
"""

from __future__ import annotations

import argparse
import os
import sys

from eval_runner import __version__
from eval_runner.auth import AuthError, provider_from_env
from eval_runner.config import ConfigError, load_config
from eval_runner.dataverse import DataverseError, sink_from_env
from eval_runner.gate import GateResult, check_methods_ever_seen, evaluate_gate
from eval_runner.pp_client import ApiError, EvaluationClient
from eval_runner.reporters import print_console, print_gate, write_json, write_junit
from eval_runner.runner import execute, plan_executions


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader so the pack has no extra dependency."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Copilot Studio agent evaluations.")
    parser.add_argument("--config", default="config/agents.json")
    parser.add_argument("--agent", action="append", help="Agent key (repeatable).")
    parser.add_argument("--suite", action="append", help="Suite name (repeatable).")
    parser.add_argument("--out", default="results", help="Output directory.")
    parser.add_argument("--no-gate", action="store_true", help="Report only; always exit 0.")
    parser.add_argument("--no-persist", action="store_true", help="Skip Dataverse persistence.")
    parser.add_argument("--list-test-sets", metavar="AGENT_KEY",
                        help="List the agent's test sets and exit.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    load_dotenv()
    print(f"Copilot Studio evaluation runner {__version__}")

    try:
        config = load_config(args.config)
        tokens = provider_from_env()
    except (ConfigError, AuthError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Discovery helper - the fastest way to find the exact displayName to
    # put in config, and to confirm auth works at all.
    if args.list_test_sets:
        try:
            agent = config.agent(args.list_test_sets)
            client = EvaluationClient(
                tokens, agent.environment_id, agent.bot_id,
                base_url=config.base_url, api_version=config.api_version,
            )
            print(f"\nTest sets for {agent.display_name}:")
            for test_set in client.list_test_sets():
                print(
                    f"  {test_set.get('displayName')!r}  "
                    f"id={test_set.get('id')}  state={test_set.get('state')}  "
                    f"cases={test_set.get('totalTestCases')}"
                )
            return 0
        except (ConfigError, ApiError, AuthError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    try:
        plan = plan_executions(config, agent_keys=args.agent, suite_filter=args.suite)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not plan:
        print("Nothing to run for the given filters.", file=sys.stderr)
        return 2

    print(f"Planned {len(plan)} execution(s):")
    for item in plan:
        print(f"  - {item['label']}")
    print()

    executions = execute(config, tokens, plan)
    print_console(executions)

    # --- persistence -------------------------------------------------
    persisted: list[dict] = []
    if not args.no_persist:
        try:
            sink = sink_from_env()
        except DataverseError as exc:
            sink = None
            print(f"\n  ! Dataverse not configured correctly: {exc}")
        if sink:
            print("\n  Persisting results to Dataverse...")
            for execution in executions:
                if execution["error"]:
                    continue
                try:
                    outcome = sink.persist_execution(execution, context={
                        "agentKey": execution["agentKey"],
                        "agentDisplayName": execution["agentDisplayName"],
                        "environmentId": execution["environmentId"],
                        "botId": execution["botId"],
                        "environmentTier": os.environ.get("ENVIRONMENT_TIER", ""),
                        "solutionVersion": os.environ.get("SOLUTION_VERSION", ""),
                        "commitSha": os.environ.get("GITHUB_SHA", os.environ.get("BUILD_SOURCEVERSION", "")),
                        "persona": execution["persona"],
                        "suite": execution["suite"],
                        "category": execution["category"],
                        "testSetName": execution["testSetName"],
                    })
                    persisted.append({"label": execution["label"], **outcome})
                    print(f"    {execution['label']}: {outcome['metricRowsWritten']} metric row(s)")
                except DataverseError as exc:
                    print(f"    ! {execution['label']}: {exc}")

    # --- gate --------------------------------------------------------
    gate = GateResult(passed=True)
    errored = [e for e in executions if e["error"]]
    for execution in executions:
        if execution["error"]:
            continue
        agent = config.agent(execution["agentKey"])
        gate = gate.merge(
            evaluate_gate(execution["summary"], agent.thresholds, label=execution["label"])
        )

    # One config-sanity check per agent, rather than a "not present" note on
    # every suite that legitimately does not use a given method.
    for agent_key in sorted({e["agentKey"] for e in executions if not e["error"]}):
        agent = config.agent(agent_key)
        summaries = [
            e["summary"] for e in executions
            if e["agentKey"] == agent_key and not e["error"]
        ]
        gate = gate.merge(check_methods_ever_seen(summaries, agent.thresholds, agent_key))
    for execution in errored:
        if execution["required"]:
            gate = gate.merge(GateResult(
                passed=False,
                violations=[f"[{execution['label']}] run did not complete: {execution['error']}"],
            ))
        else:
            gate.notes.append(f"[{execution['label']}] optional suite errored: {execution['error']}")

    print_gate(gate)

    payload = {
        "version": __version__,
        "gate": {"passed": gate.passed, "violations": gate.violations, "notes": gate.notes},
        "persisted": persisted,
        "executions": [
            {k: v for k, v in e.items() if k != "raw"} for e in executions
        ],
    }
    json_path = write_json(payload, args.out)
    junit_path = write_junit(executions, args.out)
    print(f"\n  JSON  : {json_path}")
    print(f"  JUnit : {junit_path}")

    if args.no_gate:
        return 0
    if errored and any(e["required"] for e in errored):
        return 3
    return 0 if gate.passed else 1


if __name__ == "__main__":
    sys.exit(main())
