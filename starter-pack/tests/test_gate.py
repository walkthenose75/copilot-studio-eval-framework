"""Quality-gate logic - the safety-critical core.

These lock in the fail-safe posture: the gate must never PASS on absent or
unclassifiable evidence, and must never pass while a configured hard-stop
method was never evaluated. They are the executable form of the D1 defect
recorded in ``.github/PROVENANCE.md`` - if any of these ever go green while
asserting ``passed``, the fail-open regression is back.

Pure logic: no network, no tenant, no auth.
"""

from __future__ import annotations

from eval_runner.config import Thresholds
from eval_runner.gate import GateResult, check_methods_ever_seen, evaluate_gate
from eval_runner.pp_client import summarize


def rec(method: str, outcome: str) -> dict:
    return {"method": method, "outcome": outcome}


def summary_of(*records: dict) -> dict:
    return summarize(list(records))


# -- the gate must not pass without gradeable evidence ---------------------

def test_healthy_run_passes():
    th = Thresholds(fail_on_any=["ContentSafety"], min_overall_pass_rate=0.9)
    summary = summary_of(*([rec("CompareMeaning", "pass")] * 10 + [rec("ContentSafety", "pass")]))
    result = evaluate_gate(summary, th)
    assert result.passed
    assert result.violations == []


def test_zero_results_fails():
    result = evaluate_gate(summary_of(), Thresholds(min_overall_pass_rate=0.9))
    assert not result.passed
    assert any("scored result" in v for v in result.violations)


def test_all_unknown_fails():
    # min_scored_results=0 isolates the fail_on_unknown rule from the
    # "no evidence" rule; both should independently forbid a pass here.
    result = evaluate_gate(summary_of(rec("X", "unknown"), rec("X", "unknown")),
                           Thresholds(min_scored_results=0))
    assert not result.passed
    assert any("classify" in v for v in result.violations)


def test_safety_unknown_with_functional_green_fails():
    # The dangerous case: functional tests pass, but the safety evaluator
    # returned an unclassifiable token. Promotion here means safety was never
    # actually verified.
    th = Thresholds(fail_on_any=["ContentSafety"])
    summary = summary_of(*([rec("CompareMeaning", "pass")] * 5 + [rec("ContentSafety", "unknown")]))
    assert not evaluate_gate(summary, th).passed


def test_min_scored_results_not_met_fails():
    th = Thresholds(min_scored_results=5)
    summary = summary_of(rec("CompareMeaning", "pass"), rec("CompareMeaning", "pass"))
    result = evaluate_gate(summary, th)
    assert not result.passed
    assert any("at least 5" in v for v in result.violations)


# -- threshold enforcement -------------------------------------------------

def test_per_method_threshold_breach_fails():
    th = Thresholds(min_pass_rate_by_method={"CompareMeaning": 0.9})
    summary = summary_of(rec("CompareMeaning", "pass"), rec("CompareMeaning", "pass"),
                         rec("CompareMeaning", "pass"), rec("CompareMeaning", "fail"))  # 75%
    result = evaluate_gate(summary, th)
    assert not result.passed
    assert any("CompareMeaning" in v for v in result.violations)


def test_overall_threshold_breach_fails():
    th = Thresholds(min_overall_pass_rate=0.9)
    summary = summary_of(*([rec("X", "pass")] * 8 + [rec("X", "fail")] * 2))  # 80%
    result = evaluate_gate(summary, th)
    assert not result.passed
    assert any("Overall" in v for v in result.violations)


def test_fail_on_any_hard_stop_fails():
    th = Thresholds(fail_on_any=["ContentSafety"], min_scored_results=0)
    summary = summary_of(rec("ContentSafety", "pass"), rec("ContentSafety", "fail"))
    result = evaluate_gate(summary, th)
    assert not result.passed
    assert any("hard stop" in v for v in result.violations)


def test_invalid_rate_exceeded_fails():
    th = Thresholds(max_invalid_rate=0.1, min_scored_results=0)
    summary = summary_of(rec("X", "pass"), rec("X", "pass"),
                         rec("X", "invalid"), rec("X", "invalid"))  # 50% invalid
    result = evaluate_gate(summary, th)
    assert not result.passed
    assert any("Invalid" in v for v in result.violations)


def test_method_matching_is_case_and_space_insensitive():
    # Config says "Content safety"; the API returns "ContentSafety".
    th = Thresholds(fail_on_any=["Content safety"], min_scored_results=0)
    assert not evaluate_gate(summary_of(rec("ContentSafety", "fail")), th).passed


def test_fail_on_unknown_false_tolerates_but_notes():
    th = Thresholds(fail_on_unknown=False, min_scored_results=1)
    summary = summary_of(rec("X", "pass"), rec("X", "pass"), rec("X", "unknown"))
    result = evaluate_gate(summary, th)
    assert result.passed
    assert any("failOnUnknownStatus" in n for n in result.notes)


# -- coverage gap: a configured hard stop that never ran -------------------

def test_hard_stop_method_never_ran_is_a_violation():
    th = Thresholds(fail_on_any=["ContentSafety"])
    result = check_methods_ever_seen([summary_of(rec("CompareMeaning", "pass"))], th, "sample-agent")
    assert not result.passed
    assert any("ContentSafety" in v for v in result.violations)


def test_unseen_soft_method_is_a_note_not_a_violation():
    th = Thresholds(min_pass_rate_by_method={"KeywordMatch": 0.9})
    result = check_methods_ever_seen([summary_of(rec("CompareMeaning", "pass"))], th, "sample-agent")
    assert result.passed
    assert result.notes


# -- GateResult composition ------------------------------------------------

def test_gateresult_merge_is_conjunctive():
    merged = GateResult(passed=True, notes=["a"]).merge(
        GateResult(passed=False, violations=["boom"]))
    assert merged.passed is False
    assert merged.violations == ["boom"]
    assert merged.notes == ["a"]
