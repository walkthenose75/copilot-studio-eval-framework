"""Result parsing and aggregation.

Covers ``classify`` token mapping, ``iter_metrics`` field-fallback and
robustness against the malformed shapes noted in PROVENANCE (null collections,
misplaced fields, ``data`` as a string), and ``summarize`` arithmetic
(pass rate excludes invalid and unknown).

The status tokens asserted here are the runner's current *guesses*; when the
shakeout maps the real tokens, update ``pp_client.py`` and these expectations
together.
"""

from __future__ import annotations

import pytest

from eval_runner.pp_client import classify, iter_metrics, summarize


# -- classify --------------------------------------------------------------

@pytest.mark.parametrize("token", ["Passed", "pass", "SUCCEEDED", "success", "true", "  Pass  "])
def test_classify_pass_tokens(token):
    assert classify(token) == "pass"


@pytest.mark.parametrize("token", ["Failed", "fail", "false", "FAIL"])
def test_classify_fail_tokens(token):
    assert classify(token) == "fail"


@pytest.mark.parametrize("token", ["Invalid", "NA", "notApplicable", "skipped", "none", "", None])
def test_classify_invalid_tokens(token):
    assert classify(token) == "invalid"


@pytest.mark.parametrize("token", ["mystery", "queued", "42"])
def test_classify_unknown_tokens(token):
    assert classify(token) == "unknown"


# -- iter_metrics ----------------------------------------------------------

def test_iter_metrics_reads_nested_result_fields():
    run = {"testCasesResults": [
        {"testCaseId": "c1", "state": "done", "metricsResults": [
            {"type": "CompareMeaning",
             "result": {"status": "Passed", "aiResultReason": "looks right", "score": 0.91}},
            {"metricType": "GeneralQuality",
             "result": {"data": {"status": "Failed", "errorReason": "off topic"}}},
        ]},
        {"testCaseId": "c2", "metricsResults": [
            {"type": "KeywordMatch", "result": {"status": "Invalid"}},
        ]},
    ]}
    records = list(iter_metrics(run))
    assert len(records) == 3
    by_method = {r["method"]: r for r in records}

    assert by_method["CompareMeaning"]["outcome"] == "pass"
    assert by_method["CompareMeaning"]["score"] == 0.91
    assert by_method["CompareMeaning"]["aiResultReason"] == "looks right"

    # status and errorReason live under result.data here, not result itself.
    assert by_method["GeneralQuality"]["outcome"] == "fail"
    assert by_method["GeneralQuality"]["errorReason"] == "off topic"

    assert by_method["KeywordMatch"]["outcome"] == "invalid"
    assert records[0]["testCaseId"] == "c1"


def test_iter_metrics_handles_empty_and_null_shapes():
    assert list(iter_metrics({})) == []
    assert list(iter_metrics({"testCasesResults": None})) == []
    assert list(iter_metrics(
        {"testCasesResults": [{"testCaseId": "c", "metricsResults": None}]})) == []


def test_iter_metrics_missing_result_degrades_to_invalid():
    run = {"testCasesResults": [
        {"testCaseId": "c1", "metricsResults": [{"type": "CompareMeaning"}]},  # no 'result'
    ]}
    records = list(iter_metrics(run))
    assert len(records) == 1
    assert records[0]["rawStatus"] is None
    assert records[0]["outcome"] == "invalid"


def test_iter_metrics_data_as_string_is_ignored_safely():
    # PROVENANCE notes 'data' has been observed as a string, not an object.
    run = {"testCasesResults": [
        {"testCaseId": "c1", "metricsResults": [
            {"type": "X", "result": {"status": "Passed", "data": "not-a-dict"}},
        ]},
    ]}
    assert list(iter_metrics(run))[0]["outcome"] == "pass"


# -- summarize -------------------------------------------------------------

def test_summarize_pass_rate_excludes_invalid_and_unknown():
    records = [
        {"method": "X", "outcome": "pass"},
        {"method": "X", "outcome": "pass"},
        {"method": "X", "outcome": "fail"},
        {"method": "X", "outcome": "invalid"},
        {"method": "X", "outcome": "unknown"},
    ]
    summary = summarize(records)
    bucket = summary["byMethod"]["X"]
    assert (bucket["pass"], bucket["fail"], bucket["invalid"], bucket["unknown"]) == (2, 1, 1, 1)
    assert bucket["passRate"] == pytest.approx(2 / 3)      # invalid + unknown excluded
    assert summary["totals"]["passRate"] == pytest.approx(2 / 3)
    assert summary["metricCount"] == 5


def test_summarize_no_scored_results_has_none_rate():
    summary = summarize([{"method": "X", "outcome": "invalid"}])
    assert summary["byMethod"]["X"]["passRate"] is None
    assert summary["totals"]["passRate"] is None


def test_summarize_empty():
    summary = summarize([])
    assert summary["metricCount"] == 0
    assert summary["totals"]["passRate"] is None
    assert summary["byMethod"] == {}
