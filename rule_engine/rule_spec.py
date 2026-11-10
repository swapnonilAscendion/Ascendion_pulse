"""
The structured rule the AI must return, and its validation.

The AI never writes SQL. It fills this spec; sql_builder turns a VALID spec into SQL
using names from schema_config. That keeps AI output away from the database.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from . import schema_config as cfg


@dataclass
class Condition:
    attribute: str          # physical Employee column name, e.g. "Grade"
    operator: str           # one of cfg.OPERATORS
    value: str              # IN / NOT IN: comma-separated, e.g. "Chennai, Pune"

    def values(self) -> list[str]:
        if self.operator in cfg.LIST_OPERATORS:
            return [v.strip() for v in self.value.split(cfg.LIST_SEPARATOR) if v.strip()]
        return [self.value.strip()]


@dataclass
class RuleSpec:
    rule_name: str
    themes: list[str] = field(default_factory=list)          # exact ThemeName values
    question_ids: list[int] = field(default_factory=list)    # optional: specific questions
    conditions: list[Condition] = field(default_factory=list)
    description: str | None = None
    trigger_frequency: str | None = None
    effective_from: str | None = None                        # YYYY-MM-DD
    effective_to: str | None = None
    priority: int = 1
    source_text: str | None = None                           # the English rule HR typed
    assumptions: list[str] = field(default_factory=list)     # what the AI guessed - shown to HR
    needs_clarification: str | None = None                   # set when the rule cannot be built

    @classmethod
    def from_dict(cls, d: dict) -> RuleSpec:
        d = dict(d)
        d["conditions"] = [Condition(**c) for c in d.get("conditions") or []]
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


# JSON shape given to the AI (kept next to the dataclass so they change together).
SPEC_JSON_SHAPE = """{
  "rule_name": "short business name",
  "description": "one-sentence plain-English summary for HR",
  "themes": ["exact ThemeName", "..."],
  "question_ids": [],
  "conditions": [{"attribute": "<Employee column>", "operator": "<operator>", "value": "<value or comma-separated list>"}],
  "trigger_frequency": "<frequency or null>",
  "effective_from": "YYYY-MM-DD or null",
  "effective_to": "YYYY-MM-DD or null",
  "priority": 1,
  "assumptions": ["anything you had to guess"],
  "needs_clarification": null
}"""


def _parse_date(s: str | None, label: str, errors: list[str]) -> date | None:
    if s is None:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        errors.append(f"{label} '{s}' is not a YYYY-MM-DD date.")
        return None


def validate(spec: RuleSpec) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings). Errors block SQL generation; warnings are shown to HR."""
    errors: list[str] = []
    warnings: list[str] = []

    if spec.needs_clarification:
        errors.append(f"AI needs clarification: {spec.needs_clarification}")
    if not spec.rule_name or not spec.rule_name.strip():
        errors.append("rule_name is empty.")
    if not spec.themes and not spec.question_ids:
        errors.append("No questions selected: give at least one theme or question id.")

    known_themes = {t.lower(): t for t in cfg.KNOWN_VALUES.get("theme", [])}
    for t in spec.themes:
        if known_themes and t.lower() not in known_themes:
            errors.append(f"Unknown theme '{t}'. Known: {', '.join(known_themes.values())}.")

    attrs = cfg.condition_attributes()
    for c in spec.conditions:
        if c.attribute not in attrs:
            errors.append(f"Attribute '{c.attribute}' is not allowed. Allowed: {', '.join(attrs)}.")
            continue
        if c.operator not in cfg.OPERATORS:
            errors.append(f"Operator '{c.operator}' is not allowed. Allowed: {', '.join(cfg.OPERATORS)}.")
            continue
        vals = c.values()
        if not vals:
            errors.append(f"Condition on {c.attribute} has no value.")
        if len(vals) > 1 and c.operator not in cfg.LIST_OPERATORS:
            errors.append(f"Condition on {c.attribute} has several values; use IN / NOT IN.")
        key = attrs[c.attribute]
        if key == "grade" and c.operator in {">", ">=", "<", "<="}:
            if not re.fullmatch(rf"{re.escape(cfg.GRADE_PREFIX)}\d+", vals[0]):
                errors.append(f"Grade comparison needs a value like {cfg.GRADE_PREFIX}5, got '{vals[0]}'.")
        if key == "date_of_joining":
            for v in vals:
                _parse_date(v, "DateOfJoining value", errors)
        known = cfg.KNOWN_VALUES.get(key)
        if known:
            for v in vals:
                if v.lower() not in {k.lower() for k in known}:
                    warnings.append(f"'{v}' is not a known {c.attribute} value - check spelling.")

    if spec.trigger_frequency and spec.trigger_frequency not in cfg.TRIGGER_FREQUENCIES:
        errors.append(f"trigger_frequency '{spec.trigger_frequency}' not in {cfg.TRIGGER_FREQUENCIES}.")
    start = _parse_date(spec.effective_from, "effective_from", errors)
    end = _parse_date(spec.effective_to, "effective_to", errors)
    if start and end and end < start:
        errors.append("effective_to is before effective_from.")
    if not isinstance(spec.priority, int) or spec.priority < 1:
        errors.append("priority must be an integer >= 1.")
    if not spec.conditions:
        warnings.append("No conditions: this rule targets ALL active employees.")
    warnings += [f"AI assumption: {a}" for a in spec.assumptions]
    return errors, warnings
