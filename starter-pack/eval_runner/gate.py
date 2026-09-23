"""Release quality gate.

Gating rules, in order of severity:
  1. fail_on_any  - any single failure in these methods blocks the release
                    (use for ContentSafety and your security Custom method)
  2. per-method minimum pass rates
  3. overall minimum pass rate
  4. maximum share of Invalid results (a suite full of Invalid results is a
     broken suite, not a passing one - Invalid means the test case was missing
     an expected answer or keywords)

Deliberately NOT implemented: a single blended score across methods.
'Compare meaning' and 'general quality' measure different things; averaging
them produces a number that cannot be acted on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Thresholds


@dataclass
class GateResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def merge(self, other: "GateResult") -> "GateResult":
        return GateResult(
            passed=self.passed and other.passed,
            violations=self.violations + other.violations,
            notes=self.notes + other.notes,
        )


def evaluate_gate(
    summary: dict,
    thresholds: Thresholds,
    label: str = "",
    quiet_missing: bool = True,
) -> GateResult:
    """Apply thresholds to one execution's summary.

    A threshold only applies to a method that actually ran. A suite legitimately
    uses a subset of methods, so "method not present" is normal here and is
    silent by default - reporting it per suite buries the real violations.
    Config typos are caught once per agent instead, by
    ``check_methods_ever_seen`` below.
    """
    prefix = f"[{label}] " if label else ""
    violations: list[str] = []
    notes: list[str] = []

    by_method = summary.get("byMethod", {})
    totals = summary.get("totals", {})

    # 0a. No evidence is not a pass.
    scored = totals.get("pass", 0) + totals.get("fail", 0)
    if scored < thresholds.min_scored_results:
        violations.append(
            f"{prefix}Only {scored} scored result(s); at least "
            f"{thresholds.min_scored_results} required. A run that produced no "
            "gradeable results cannot demonstrate quality - check the agent, the "
            "test set, and the user profile's permissions."
        )

    # 0b. Unscoreable results block the gate.
    unknown = totals.get("unknown", 0)
    if unknown and thresholds.fail_on_unknown:
        violations.append(
            f"{prefix}{unknown} result(s) returned a status token this runner "
            "cannot classify, so they were not scored. Map them in "
            "eval_runner/pp_client.py (see SHAKEDOWN.md step 2) before trusting "
            "this gate."
        )

    # 1. hard stops
    for method in thresholds.fail_on_any:
        bucket = _match_method(by_method, method)
        if bucket is None:
            if not quiet_missing:
                notes.append(f"{prefix}No results for hard-stop method '{method}'.")
            continue
        if bucket["fail"] > 0:
            violations.append(
                f"{prefix}{bucket['fail']} failure(s) in '{method}' - hard stop."
            )

    # 2. per-method pass rates
    for method, minimum in thresholds.min_pass_rate_by_method.items():
        bucket = _match_method(by_method, method)
        if bucket is None:
            if not quiet_missing:
                notes.append(
                    f"{prefix}No results for method '{method}' (threshold {minimum:.0%})."
                )
            continue
        rate = bucket.get("passRate")
        if rate is None:
            notes.append(f"{prefix}Method '{method}' produced no scored results.")
            continue
        if rate < minimum:
            violations.append(
                f"{prefix}'{method}' pass rate {rate:.1%} is below the "
                f"{minimum:.0%} threshold ({bucket['pass']}/{bucket['pass'] + bucket['fail']})."
            )

    # 3. overall
    if thresholds.min_overall_pass_rate is not None:
        rate = totals.get("passRate")
        if rate is None:
            notes.append(f"{prefix}No scored results to compute an overall pass rate.")
        elif rate < thresholds.min_overall_pass_rate:
            violations.append(
                f"{prefix}Overall pass rate {rate:.1%} is below the "
                f"{thresholds.min_overall_pass_rate:.0%} threshold."
            )

    # 4. invalid share
    if thresholds.max_invalid_rate is not None:
        total_metrics = summary.get("metricCount", 0)
        if total_metrics:
            invalid_rate = totals.get("invalid", 0) / total_metrics
            if invalid_rate > thresholds.max_invalid_rate:
                violations.append(
                    f"{prefix}{invalid_rate:.1%} of results are Invalid, above the "
                    f"{thresholds.max_invalid_rate:.0%} limit. Test cases are probably "
                    "missing expected answers or keywords."
                )

    if unknown and not thresholds.fail_on_unknown:
        notes.append(
            f"{prefix}{unknown} unclassified result(s) tolerated because "
            "failOnUnknownStatus is false. Check rawStatus in the JSON output."
        )

    return GateResult(passed=not violations, violations=violations, notes=notes)


def _match_method(by_method: dict, method: str) -> dict | None:
    """Match a method name case-insensitively, ignoring spaces.

    Lets config say "Content safety", "ContentSafety" or "contentsafety" and
    still line up with whatever token the API returns.
    """
    target = method.strip().lower().replace(" ", "").replace("_", "")
    for name, bucket in by_method.items():
        if str(name).strip().lower().replace(" ", "").replace("_", "") == target:
            return bucket
    return None


def check_methods_ever_seen(summaries: list[dict], thresholds: Thresholds,
                            agent_label: str) -> GateResult:
    """Catch configured methods that never appeared in ANY of an agent's runs.

    That is almost always a typo in the method name, or a suite that was never
    wired up - either way a threshold that silently never applies is worse than
    no threshold at all.
    """
    seen: set[str] = set()
    for summary in summaries:
        seen.update(summary.get("byMethod", {}).keys())
    merged = {name: {} for name in seen}

    notes: list[str] = []
    violations: list[str] = []
    hard_stops = {m.strip().lower().replace(" ", "") for m in thresholds.fail_on_any}
    configured = set(thresholds.min_pass_rate_by_method) | set(thresholds.fail_on_any)

    for method in sorted(configured):
        if _match_method(merged, method) is not None:
            continue
        key = method.strip().lower().replace(" ", "")
        if key in hard_stops:
            # A safety or security method that never ran is a coverage failure,
            # not a footnote. Silently "passing" here means promoting an agent
            # whose safety was never evaluated at all.
            violations.append(
                f"[{agent_label}] '{method}' is configured as a hard stop but NO "
                "run produced results for it. The agent was never evaluated for "
                "this. Either add a test set that uses it, or remove it from "
                "failOnAnyFailureIn - do not leave it unverified."
            )
        else:
            notes.append(
                f"[{agent_label}] Threshold configured for '{method}' but no run "
                "produced results for that method. Check the name against the test "
                "methods actually used by this agent's test sets."
            )
    return GateResult(passed=not violations, violations=violations, notes=notes)
