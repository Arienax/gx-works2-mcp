#!/usr/bin/env python3
"""Compare real API prompt assembly without calling a model or GX.

Run inside the patched checkout. Cases are JSONL objects with id, request,
optional plc_model/target_mode/confirmed_spec/current_version_json/is_edit_mode.
Only counts, hashes and selection reasons are written, never prompt bodies.
This tool measures context, NOT generated-program correctness.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policies", nargs="+", default=["legacy", "minimal", "manual", "examples", "combined", "adaptive"])
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose another path")
    from prompt_context_policy import ContextAudit, context_policy_scope, resolve_context_policy
    policies = [resolve_context_policy(name).name for name in args.policies]
    if len(set(policies)) != len(policies):
        parser.error("Duplicate policies")
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not isinstance(case.get("request"), str):
            parser.error("Each case needs string id and request fields")
        if case["id"] in ids:
            parser.error("Duplicate case id")
        ids.add(case["id"])
        if case.get("target_mode", "ladder") not in ("ladder", "st"):
            parser.error("This auditor covers API Ladder/ST, not native FBD or tool-agent runs")
    import api
    rows = []
    for case in cases:
        for policy in policies:
            collector = ContextAudit()
            with context_policy_scope(policy, audit=collector):
                messages, _, should_persist = api._prepare_api_call(
                    case["request"], "offline-context-audit", "high", case.get("target_mode", "ladder"),
                    is_edit_mode=bool(case.get("is_edit_mode", False)),
                    conversation_history=[], confirmed_spec=case.get("confirmed_spec"),
                    current_version_json=case.get("current_version_json"),
                    plc_model=case.get("plc_model", "FX3U"), persist_history=False,
                )
                if should_persist:
                    raise RuntimeError("Offline audit must not save conversation history")
                report = collector.request(messages)
            rows.append({"case_id": case["id"], "target_mode": case.get("target_mode", "ladder"),
                         "plc_model": case.get("plc_model", "FX3U"), **report})
    result = {"schema_version": 1, "measurement": "offline_prompt_assembly_not_model_performance",
              "model_called": False, "gx_called": False, "cases": len(cases), "rows": rows}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"cases": len(cases), "policies": policies, "rows": len(rows),
                      "model_called": False, "gx_called": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
