"""Console, JSON and JUnit XML output.

JUnit XML means any CI system renders per-test-case results natively, with no
custom pipeline UI work.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def write_json(payload: dict, out_dir: str, name: str = "results") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}-{_now()}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return path


def write_junit(executions: list[dict], out_dir: str, name: str = "junit") -> str:
    """One <testsuite> per agent/suite/persona execution, one <testcase> per metric."""
    os.makedirs(out_dir, exist_ok=True)
    suites = ET.Element("testsuites")

    for execution in executions:
        label = execution["label"]
        records = execution.get("records", [])
        failures = sum(1 for r in records if r["outcome"] == "fail")
        skipped = sum(1 for r in records if r["outcome"] in ("invalid", "unknown"))
        suite = ET.SubElement(
            suites,
            "testsuite",
            name=label,
            tests=str(len(records)),
            failures=str(failures),
            skipped=str(skipped),
            errors="0",
        )
        for record in records:
            case = ET.SubElement(
                suite,
                "testcase",
                classname=f"{label}.{record.get('method') or 'unknown'}",
                name=str(record.get("testCaseId") or "case"),
            )
            if record["outcome"] == "fail":
                message = record.get("aiResultReason") or record.get("errorReason") or "Test failed"
                failure = ET.SubElement(case, "failure", message=str(message)[:500])
                failure.text = json.dumps(record, indent=2, default=str)
            elif record["outcome"] in ("invalid", "unknown"):
                ET.SubElement(
                    case,
                    "skipped",
                    message=f"status={record.get('rawStatus')}",
                )

    path = os.path.join(out_dir, f"{name}-{_now()}.xml")
    ET.ElementTree(suites).write(path, encoding="utf-8", xml_declaration=True)
    return path


def print_console(executions: list[dict]) -> None:
    for execution in executions:
        summary = execution["summary"]
        totals = summary["totals"]
        rate = totals.get("passRate")
        rate_text = f"{rate:.1%}" if rate is not None else "n/a"
        print()
        print(f"  {execution['label']}")
        print(f"    run {execution.get('runId')}  state={execution.get('state')}")
        print(
            f"    {totals['pass']} passed  {totals['fail']} failed  "
            f"{totals['invalid']} invalid  {totals['unknown']} unknown   pass rate {rate_text}"
        )
        for method, bucket in sorted(summary["byMethod"].items()):
            method_rate = bucket.get("passRate")
            method_text = f"{method_rate:.1%}" if method_rate is not None else "n/a"
            print(
                f"      - {method:<20} {bucket['pass']:>3} pass  {bucket['fail']:>3} fail  "
                f"{bucket['invalid']:>3} invalid   {method_text}"
            )
        # The reason text is the highest-value diagnostic: group it.
        reasons: dict[str, int] = {}
        for record in execution.get("records", []):
            if record["outcome"] == "fail":
                reason = (record.get("aiResultReason") or record.get("errorReason") or "").strip()
                if reason:
                    key = reason[:160]
                    reasons[key] = reasons.get(key, 0) + 1
        if reasons:
            print("      top failure reasons:")
            for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]:
                print(f"        ({count}x) {reason}")


def print_gate(gate) -> None:
    print()
    if gate.passed:
        print("  GATE: PASS")
    else:
        print("  GATE: FAIL")
        for violation in gate.violations:
            print(f"    x {violation}")
    for note in gate.notes:
        print(f"    - {note}")
