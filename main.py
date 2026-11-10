"""
Ascendion Pulse - Rules Manager engine CLI.

  python main.py ddl                                     regenerate rule_engine/sql/01_schema.sql
  python main.py prompt                                  print the AI system prompt (paste into AI Builder / Copilot Studio)
  python main.py rule "For November send Culture & Inclusion questions to G5 in Chennai"
  python main.py rule "..." --provider azure             same, using Azure OpenAI
  python main.py rule --spec-file spec.json              build SQL from JSON returned by another tool
  python main.py eval --provider mock                    score a provider against rule_engine/eval_cases.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from rule_engine import ddl, llm
from rule_engine.rule_spec import RuleSpec, validate
from rule_engine.sql_builder import build_insert_sql, build_preview_sql

ROOT = Path(__file__).parent / "rule_engine"


def cmd_ddl(_args) -> int:
    out = ROOT / "sql" / "01_schema.sql"
    out.parent.mkdir(exist_ok=True)
    out.write_text(ddl.schema_ddl(), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


def cmd_prompt(args) -> int:
    print(llm.build_system_prompt(args.today))
    return 0


def cmd_rule(args) -> int:
    if args.spec_file:
        raw = json.loads(Path(args.spec_file).read_text(encoding="utf-8"))
    elif args.text:
        raw = llm.generate(args.text, args.provider, args.today)
    else:
        print("Give rule text or --spec-file.", file=sys.stderr)
        return 2

    spec = RuleSpec.from_dict(raw)
    errors, warnings = validate(spec)
    print("== Rule spec ==")
    print(json.dumps(spec.to_dict(), indent=2))
    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        return 1

    print("\n== Preview SQL (read-only) ==")
    print(build_preview_sql(spec))
    print("== Insert SQL (run after HR approval) ==")
    print(build_insert_sql(spec, created_by=args.created_by))
    return 0


def _normalise(spec: dict) -> dict:
    def cond_key(c):
        attr, op, val = (c["attribute"], c["operator"], c["value"]) if isinstance(c, dict) else c
        return attr.lower(), op.upper(), ",".join(sorted(v.strip().lower() for v in str(val).split(",")))
    return {
        "themes": sorted(t.lower() for t in spec.get("themes") or []),
        "conditions": sorted(cond_key(c) for c in spec.get("conditions") or []),
        "effective_from": spec.get("effective_from"),
        "effective_to": spec.get("effective_to"),
    }


def cmd_eval(args) -> int:
    suite = json.loads((ROOT / "eval_cases.json").read_text(encoding="utf-8"))
    today = date.fromisoformat(suite["reference_date"])
    passed = 0
    for i, case in enumerate(suite["cases"], 1):
        expected = case["expected"]
        try:
            got = llm.generate(case["text"], args.provider, today)
        except Exception as exc:  # a provider error counts as a failed case, not a crash
            print(f"[{i:02}] FAIL  {case['text']}\n      provider error: {exc}")
            continue
        if expected.get("needs_clarification"):
            ok = bool(got.get("needs_clarification"))
        else:
            ok = not got.get("needs_clarification") and _normalise(got) == _normalise(expected)
        passed += ok
        print(f"[{i:02}] {'PASS' if ok else 'FAIL'}  {case['text']}")
        if not ok and args.verbose:
            print(f"      expected: {_normalise(expected) if not expected.get('needs_clarification') else expected}")
            print(f"      got:      {_normalise(got)}  clarification={got.get('needs_clarification')}")
    total = len(suite["cases"])
    print(f"\n{args.provider}: {passed}/{total} passed ({passed / total:.0%})")
    return 0 if passed == total else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Ascendion Pulse Rules Manager engine")
    p.add_argument("--today", type=date.fromisoformat, default=date.today(), help="override today's date (YYYY-MM-DD)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ddl", help="regenerate the schema script").set_defaults(fn=cmd_ddl)
    sub.add_parser("prompt", help="print the AI system prompt").set_defaults(fn=cmd_prompt)

    r = sub.add_parser("rule", help="English rule -> spec -> SQL")
    r.add_argument("text", nargs="?")
    r.add_argument("--provider", choices=list(llm.PROVIDERS), default="mock")
    r.add_argument("--spec-file", help="JSON spec produced elsewhere (AI Builder, Copilot Studio)")
    r.add_argument("--created-by", default=None)
    r.set_defaults(fn=cmd_rule)

    e = sub.add_parser("eval", help="score a provider on eval_cases.json")
    e.add_argument("--provider", choices=list(llm.PROVIDERS), default="mock")
    e.add_argument("-v", "--verbose", action="store_true")
    e.set_defaults(fn=cmd_eval)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
