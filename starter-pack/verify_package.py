#!/usr/bin/env python3
"""Offline self-check. Validates the package without needing auth or a tenant.

Run this first in a fresh clone, and after any edit, to confirm nothing is
structurally broken before spending time on live calls.

    python verify_package.py
"""

from __future__ import annotations

import ast
import csv
import glob
import json
import os
import sys

FAIL: list[str] = []
WARN: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def main() -> int:
    print("\nPython syntax")
    for path in sorted(glob.glob("eval_runner/*.py")) + ["evaluate.py", "dataverse/provision_schema.py"]:
        try:
            ast.parse(open(path, encoding="utf-8").read())
            check(path, True)
        except SyntaxError as exc:
            check(path, False, str(exc))

    print("\nConfiguration")
    try:
        cfg = json.load(open("config/agents.json", encoding="utf-8"))
        check("config/agents.json parses", True)
        agent = cfg["agents"][0]
        check("runOnPublishedBot present", "runOnPublishedBot" in agent,
              "a gate must never inherit an undocumented default")
        th = agent.get("thresholds", {})
        check("minScoredResults set", "minScoredResults" in th,
              "without it the gate can pass on an empty result set")
        check("failOnUnknownStatus enabled", th.get("failOnUnknownStatus") is True,
              "unclassifiable results must block, not slip through")
        personas = {p["name"] for p in cfg.get("personas", [])}
        for suite in agent.get("suites", []):
            for persona in suite.get("personas", []):
                check(f"persona '{persona}' defined", persona in personas)
    except Exception as exc:  # noqa: BLE001
        check("config/agents.json", False, str(exc))

    print("\nTest set CSVs (documented import limits)")
    for path in sorted(glob.glob("testsets/*.csv")):
        rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
        header_ok = rows and rows[0] == ["Question", "Expected response"]
        count_ok = len(rows) - 1 <= 100
        len_ok = all(len(r[0]) <= 1000 for r in rows[1:] if r)
        shape_ok = all(len(r) == 2 for r in rows[1:] if r)
        check(f"{path} ({len(rows) - 1} questions)",
              header_ok and count_ok and len_ok and shape_ok)

    print("\nDataverse schema vs writer")
    try:
        schema = json.load(open("dataverse/schema.json", encoding="utf-8"))
        defined = {t["primaryName"]["name"].lower() for t in schema["tables"]}
        for table in schema["tables"]:
            defined |= {c["name"].lower() for c in table["columns"]}
        src = open("eval_runner/dataverse.py", encoding="utf-8").read()
        import re
        used = {m.lower() for m in re.findall(r'self\.col\("([^"]+)"\)', src)}
        used |= {m.lower() for m in re.findall(r"self\.col\('([^']+)'\)", src)}
        # The lookup binding is defined by the relationship, not a column.
        lookups = {r["lookupName"].lower() for r in schema.get("relationships", [])}
        missing = used - defined - lookups
        check(f"all {len(used)} written columns defined in schema",
              not missing, f"missing: {sorted(missing)}" if missing else "")

        tables = {t["name"] for t in schema["tables"]}
        used_tables = set(re.findall(r'self\.table\("([^"]+)"\)', src))
        check("all written tables defined", not (used_tables - tables))
    except Exception as exc:  # noqa: BLE001
        check("dataverse schema check", False, str(exc))

    print("\nWorkflow YAML")
    try:
        import yaml
        for path in sorted(glob.glob("workflows/*.yml")) + sorted(glob.glob("azure/*.yml")):
            yaml.safe_load(open(path, encoding="utf-8"))
            check(path, True)
    except ImportError:
        WARN.append("PyYAML not installed - workflow YAML not validated")
        print("  [WARN] PyYAML not installed; skipped")
    except Exception as exc:  # noqa: BLE001
        check("workflow YAML", False, str(exc))

    print("\nGate safety (regression guard for the fail-open defect)")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from eval_runner.config import Thresholds
        from eval_runner.gate import evaluate_gate, check_methods_ever_seen
        from eval_runner.pp_client import summarize
        th = Thresholds(fail_on_any=["ContentSafety"], min_overall_pass_rate=0.9)
        vacuous = {
            "zero results": [],
            "all unknown": [{"method": "X", "outcome": "unknown"}],
            "safety unknown + functional green":
                [{"method": "CompareMeaning", "outcome": "pass"}] * 5
                + [{"method": "ContentSafety", "outcome": "unknown"}],
        }
        for name, recs in vacuous.items():
            g = evaluate_gate(summarize(recs), th, label="guard")
            check(f"gate FAILS on {name}", not g.passed, "must never pass on absent evidence")
        g = check_methods_ever_seen(
            [summarize([{"method": "CompareMeaning", "outcome": "pass"}])], th, "guard")
        check("gate FAILS when a hard-stop method never ran", not g.passed)
        g = evaluate_gate(summarize(
            [{"method": "CompareMeaning", "outcome": "pass"}] * 10
            + [{"method": "ContentSafety", "outcome": "pass"}]), th, label="guard")
        check("gate PASSES on a healthy run", g.passed, "guard must not be over-strict")
    except Exception as exc:  # noqa: BLE001
        check("gate safety checks", False, str(exc))

    print("\nHonesty check")
    for path in [".github/PROVENANCE.md", "SHAKEDOWN.md", ".github/copilot-instructions.md"]:
        check(f"{path} present", os.path.exists(path))

    print("\n" + "=" * 62)
    if FAIL:
        print(f"{len(FAIL)} CHECK(S) FAILED:")
        for item in FAIL:
            print(f"  - {item}")
    else:
        print("All offline checks passed.")
    for item in WARN:
        print(f"  WARN: {item}")
    print("\nREMINDER: these are OFFLINE checks. They prove the package is")
    print("structurally sound. They prove NOTHING about live API behaviour.")
    print("See .github/PROVENANCE.md, then run SHAKEDOWN.md.")
    print("=" * 62 + "\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
