"""Reporter output: JSON round-trip, JUnit XML shape, console safety.

JUnit correctness matters because CI systems render pass/fail natively from it
- a malformed file or a miscounted suite silently misreports the gate.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from eval_runner.gate import GateResult
from eval_runner.reporters import print_console, print_gate, write_json, write_junit


def _execution(label: str = "agent/smoke/no-user-profile") -> dict:
    records = [
        {"testCaseId": "c1", "method": "CompareMeaning", "outcome": "pass", "rawStatus": "Passed"},
        {"testCaseId": "c2", "method": "CompareMeaning", "outcome": "fail",
         "rawStatus": "Failed", "aiResultReason": "wrong entity"},
        {"testCaseId": "c3", "method": "KeywordMatch", "outcome": "invalid", "rawStatus": "Invalid"},
        {"testCaseId": "c4", "method": "ContentSafety", "outcome": "unknown", "rawStatus": "weird"},
    ]
    return {
        "label": label,
        "runId": "run-1",
        "state": "Completed",
        "records": records,
        "summary": {
            "byMethod": {
                "CompareMeaning": {"pass": 1, "fail": 1, "invalid": 0, "unknown": 0, "passRate": 0.5},
                "KeywordMatch": {"pass": 0, "fail": 0, "invalid": 1, "unknown": 0, "passRate": None},
                "ContentSafety": {"pass": 0, "fail": 0, "invalid": 0, "unknown": 1, "passRate": None},
            },
            "totals": {"pass": 1, "fail": 1, "invalid": 1, "unknown": 1, "passRate": 0.5},
            "metricCount": 4,
        },
    }


def test_write_json_roundtrips(tmp_path):
    path = write_json({"gate": {"passed": False, "violations": ["x"]}, "n": 1}, str(tmp_path))
    with open(path, encoding="utf-8") as handle:
        reloaded = json.load(handle)
    assert reloaded["gate"]["passed"] is False
    assert reloaded["n"] == 1


def test_write_junit_counts_and_maps_outcomes(tmp_path):
    path = write_junit([_execution()], str(tmp_path))
    root = ET.parse(path).getroot()
    assert root.tag == "testsuites"

    suite = root.find("testsuite")
    assert suite.get("tests") == "4"
    assert suite.get("failures") == "1"
    assert suite.get("skipped") == "2"      # invalid + unknown both map to skipped
    assert suite.get("errors") == "0"

    cases = suite.findall("testcase")
    assert len(cases) == 4

    failing = [c for c in cases if c.find("failure") is not None]
    assert len(failing) == 1
    assert "wrong entity" in failing[0].find("failure").get("message")

    skipped = [c for c in cases if c.find("skipped") is not None]
    assert len(skipped) == 2


def test_write_junit_is_well_formed_for_empty_records(tmp_path):
    execution = _execution()
    execution["records"] = []
    path = write_junit([execution], str(tmp_path))
    suite = ET.parse(path).getroot().find("testsuite")
    assert suite.get("tests") == "0"


def test_console_and_gate_printers_do_not_raise(capsys):
    print_console([_execution()])
    print_gate(GateResult(passed=False, violations=["boom"], notes=["fyi"]))
    out = capsys.readouterr().out
    assert "GATE: FAIL" in out
    assert "boom" in out
