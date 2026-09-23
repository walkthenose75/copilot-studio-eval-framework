"""Configuration loading and validation.

Config faults must surface as ``ConfigError`` (exit code 2), never as a raw
exception that a pipeline would read as "the gate failed" (exit code 1). See
defect D2 in ``.github/PROVENANCE.md``.
"""

from __future__ import annotations

import json

import pytest

from eval_runner.config import ConfigError, load_config


def _write(tmp_path, data: dict) -> str:
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _valid() -> dict:
    return {
        "personas": [{"name": "manager", "mcsConnectionId": "${MCS_CONN_MANAGER}"}],
        "agents": [{
            "key": "sample-agent",
            "displayName": "Sample Agent",
            "environmentId": "${ENVIRONMENT_ID}",
            "botId": "${BOT_ID}",
            "suites": [
                {"name": "smoke", "testSetName": "sample-smoke-v1"},
                {"name": "security", "testSetName": "sample-sec-v1", "personas": ["manager"]},
            ],
            "thresholds": {
                "failOnAnyFailureIn": ["ContentSafety"],
                "minPassRateByMethod": {"CompareMeaning": 0.9},
                "minOverallPassRate": 0.9,
                "failOnUnknownStatus": True,
            },
        }],
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT_ID", "env-123")
    monkeypatch.setenv("BOT_ID", "bot-456")
    monkeypatch.setenv("MCS_CONN_MANAGER", "conn-789")


def test_loads_valid_config(tmp_path):
    cfg = load_config(_write(tmp_path, _valid()))
    agent = cfg.agent("sample-agent")
    assert agent.environment_id == "env-123"        # ${ENVIRONMENT_ID} expanded
    assert agent.bot_id == "bot-456"
    assert agent.run_on_published_bot is True         # safe default, always sent
    assert agent.thresholds.min_pass_rate_by_method["CompareMeaning"] == 0.9
    assert agent.thresholds.fail_on_unknown is True
    assert cfg.persona("manager").mcs_connection_id == "conn-789"


def test_run_on_published_bot_defaults_true_when_absent(tmp_path):
    data = _valid()
    data["agents"][0].pop("runOnPublishedBot", None)
    cfg = load_config(_write(tmp_path, data))
    assert cfg.agent("sample-agent").run_on_published_bot is True


def test_missing_bot_id_raises_configerror(tmp_path):
    data = _valid()
    del data["agents"][0]["botId"]
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, data))


def test_unknown_persona_reference_raises(tmp_path):
    data = _valid()
    data["agents"][0]["suites"][1]["personas"] = ["ghost"]
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, data))


def test_empty_agents_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, {"agents": [], "personas": []}))


def test_unset_env_reference_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("BOT_ID", raising=False)
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, _valid()))


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "agents.json"
    path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(path))


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "nope.json"))
