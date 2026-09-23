"""Configuration loading and validation.

Config lives in JSON (no extra dependency) and is deliberately data-driven:
adding an agent, a persona or a suite is a config change, not a code change.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any


class ConfigError(Exception):
    """Raised when configuration is missing or internally inconsistent."""


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value: Any) -> Any:
    """Recursively expand ${ENV_VAR} references inside config values.

    Keeps secrets (connection IDs, IDs that differ per environment) out of the
    committed config file.
    """
    if isinstance(value, str):
        def sub(match: re.Match) -> str:
            name = match.group(1)
            resolved = os.environ.get(name)
            if resolved is None:
                raise ConfigError(
                    f"Config references environment variable '{name}', which is not set."
                )
            return resolved

        return _ENV_PATTERN.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class Persona:
    """An identity the evaluation runs as.

    ``mcs_connection_id`` is the Microsoft Copilot Studio connection ID used as
    the evaluation's user profile. Documented lookup path:
    Power Automate > Connections > Microsoft Copilot Studio > copy the ID from
    .../connections/shared_microsoftcopilotstudio/{mcsConnectionId}/details

    When ``mcs_connection_id`` is None the evaluation runs WITHOUT
    authentication - which is a valid but very different test.
    """

    name: str
    description: str = ""
    mcs_connection_id: str | None = None


@dataclass
class Suite:
    """A named test set to run, resolved against the agent by display name."""

    name: str
    test_set_name: str
    category: str = "functional"
    personas: list[str] = field(default_factory=list)
    required: bool = True


@dataclass
class Thresholds:
    """Release gate thresholds.

    Deliberately per-method rather than a single blended score: 'compare
    meaning' answers "did it say the right thing", 'general quality' answers
    "how well did it say it". Averaging them hides which one failed.
    """

    min_pass_rate_by_method: dict[str, float] = field(default_factory=dict)
    min_overall_pass_rate: float | None = None
    max_invalid_rate: float | None = None
    fail_on_any: list[str] = field(default_factory=list)
    # A gate must never pass on absent evidence. If an execution produced fewer
    # than this many SCORED results (pass + fail), the gate fails: something is
    # wrong with the agent, the test set, or permissions - and "no data" is not
    # the same as "no problems".
    min_scored_results: int = 1
    # Unrecognised status tokens cannot be scored, so they cannot be gated on.
    # Allowing them through is a fail-OPEN, which is exactly backwards on the
    # first run against a real tenant - the moment unknown tokens are MOST
    # likely. Set false only after SHAKEDOWN.md step 2 maps every token.
    fail_on_unknown: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Thresholds":
        return cls(
            min_pass_rate_by_method={
                str(k): float(v) for k, v in (raw.get("minPassRateByMethod") or {}).items()
            },
            min_overall_pass_rate=(
                float(raw["minOverallPassRate"]) if raw.get("minOverallPassRate") is not None else None
            ),
            max_invalid_rate=(
                float(raw["maxInvalidRate"]) if raw.get("maxInvalidRate") is not None else None
            ),
            fail_on_any=[str(x) for x in (raw.get("failOnAnyFailureIn") or [])],
            min_scored_results=int(raw.get("minScoredResults", 1)),
            fail_on_unknown=bool(raw.get("failOnUnknownStatus", True)),
        )


@dataclass
class Agent:
    """One Copilot Studio agent under evaluation.

    environment_id and bot_id are visible in Copilot Studio under
    Settings > Advanced > Details.
    """

    key: str
    display_name: str
    environment_id: str
    bot_id: str
    criticality: str = "tier2"
    # Evaluate the PUBLISHED agent, not the draft. Defaults to True because a
    # release gate must measure what users actually get. The platform default
    # for this flag is not documented, so the runner always sends it
    # explicitly rather than inheriting an unknown.
    run_on_published_bot: bool = True
    suites: list[Suite] = field(default_factory=list)
    thresholds: Thresholds = field(default_factory=Thresholds)


@dataclass
class RunnerConfig:
    agents: dict[str, Agent]
    personas: dict[str, Persona]
    poll_interval_sec: int = 10
    poll_timeout_sec: int = 1800
    max_parallel_runs: int = 4
    api_version: str = "2024-10-01"
    base_url: str = "https://api.powerplatform.com"

    def agent(self, key: str) -> Agent:
        if key not in self.agents:
            known = ", ".join(sorted(self.agents)) or "(none)"
            raise ConfigError(f"Unknown agent '{key}'. Configured agents: {known}")
        return self.agents[key]

    def persona(self, name: str) -> Persona:
        if name not in self.personas:
            known = ", ".join(sorted(self.personas)) or "(none)"
            raise ConfigError(f"Unknown persona '{name}'. Configured personas: {known}")
        return self.personas[name]


def load_config(path: str) -> RunnerConfig:
    """Load and validate agents.json."""
    if not os.path.exists(path):
        raise ConfigError(f"Config file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    raw = _expand(raw)

    def req(mapping: dict, key: str, context: str):
        """Fetch a required key, failing as a ConfigError rather than KeyError.

        A raw KeyError escapes as exit code 1, which a pipeline reads as
        "the quality gate failed" - sending someone to debug an agent when the
        real problem is a typo in the config file.
        """
        if not isinstance(mapping, dict) or key not in mapping:
            raise ConfigError(f"{context} is missing the required '{key}' property.")
        value = mapping[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ConfigError(f"{context} has an empty '{key}' property.")
        return value

    personas: dict[str, Persona] = {}
    for item in raw.get("personas", []):
        persona = Persona(
            name=req(item, "name", "A persona entry"),
            description=item.get("description", ""),
            mcs_connection_id=item.get("mcsConnectionId") or None,
        )
        personas[persona.name] = persona

    agents: dict[str, Agent] = {}
    for item in raw.get("agents", []):
        agent_key = req(item, "key", "An agent entry")
        suites = []
        for s in item.get("suites", []):
            suite_name = req(s, "name", f"A suite of agent '{agent_key}'")
            suites.append(Suite(
                name=suite_name,
                test_set_name=req(
                    s, "testSetName", f"Suite '{suite_name}' of agent '{agent_key}'"
                ),
                category=s.get("category", "functional"),
                personas=s.get("personas", []) or ["__default__"],
                required=bool(s.get("required", True)),
            ))
        agent = Agent(
            key=agent_key,
            display_name=item.get("displayName", agent_key),
            environment_id=req(item, "environmentId", f"Agent '{agent_key}'"),
            bot_id=req(item, "botId", f"Agent '{agent_key}'"),
            criticality=item.get("criticality", "tier2"),
            run_on_published_bot=bool(item.get("runOnPublishedBot", True)),
            suites=suites,
            thresholds=Thresholds.from_dict(item.get("thresholds", {})),
        )
        agents[agent.key] = agent

    settings = raw.get("settings", {})
    config = RunnerConfig(
        agents=agents,
        personas=personas,
        poll_interval_sec=int(settings.get("pollIntervalSeconds", 10)),
        poll_timeout_sec=int(settings.get("pollTimeoutSeconds", 1800)),
        max_parallel_runs=int(settings.get("maxParallelRuns", 4)),
        api_version=settings.get("apiVersion", "2024-10-01"),
        base_url=settings.get("baseUrl", "https://api.powerplatform.com").rstrip("/"),
    )

    # Validate persona references now rather than half way through a run.
    for agent in config.agents.values():
        for suite in agent.suites:
            for persona_name in suite.personas:
                if persona_name == "__default__":
                    continue
                if persona_name not in config.personas:
                    raise ConfigError(
                        f"Agent '{agent.key}' suite '{suite.name}' references "
                        f"unknown persona '{persona_name}'."
                    )
    if not config.agents:
        raise ConfigError("No agents configured.")
    return config
