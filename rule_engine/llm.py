"""
English rule -> RuleSpec JSON.

Providers (pick with --provider):
  mock   Offline keyword parser. Works today with no AI access; also the deterministic
         baseline (similar to the Azure AI Language entity-extraction approach).
  azure  Azure OpenAI chat completions over REST (no SDK needed). Configure with env vars:
         AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT,
         AZURE_OPENAI_API_VERSION (optional).
For AI Builder / Copilot Studio, run `python main.py prompt` and paste the prompt there,
then feed the JSON they return to `python main.py rule --spec-file`.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import urllib.request
from datetime import date

from . import schema_config as cfg
from .rule_spec import SPEC_JSON_SHAPE

PROMPT_VERSION = "v1"


def build_system_prompt(today: date) -> str:
    emp = cfg.columns("employee")
    attrs = "\n".join(f"  - {emp[k].name}: {emp[k].desc}" for k in cfg.CONDITION_ATTRIBUTES if k in emp)
    known = "\n".join(f"  - {k}: {', '.join(v)}" for k, v in cfg.KNOWN_VALUES.items())
    return f"""You convert an HR user's plain-English pulse-survey rule into a JSON rule definition.
Today is {today.isoformat()}. Prompt version {PROMPT_VERSION}.

A rule decides WHICH employees get WHICH questions and WHEN.
- Questions are chosen by theme (exact names below) or by explicit question ids.
- Employees are chosen by conditions on Employee attributes. All conditions are ANDed.
  No conditions = all active employees.

Allowed condition attributes (use the exact name):
{attrs}
Allowed operators: {', '.join(cfg.OPERATORS)}
- For several values use IN / NOT IN with a comma-separated value, e.g. "Chennai, Pune".
- Grades look like {cfg.GRADE_PREFIX}5. "G5 and above" -> Grade >= G5. "above G5" -> Grade > G5.
Allowed trigger_frequency: {', '.join(cfg.TRIGGER_FREQUENCIES)}

Known values (map the user's words to these exact spellings):
{known}

Dates:
- "for <Month>" without a year means the next occurrence of that month, counting the current
  month: effective_from = first day, effective_to = last day, trigger_frequency = "Monthly".
- No date mentioned -> effective_from and effective_to are null.

Rules:
- Return ONLY JSON in exactly this shape:
{SPEC_JSON_SHAPE}
- Never invent themes, attributes or operators. Use only the lists above.
- If something is ambiguous, make the most reasonable choice and say so in "assumptions".
- If the rule cannot be built (e.g. no way to tell which questions), set "needs_clarification"
  to a short question for the HR user.
- Never include SQL."""


# --------------------------------------------------------------------------- mock provider
_THEME_ALIASES = {  # extra words the mock maps to themes; the real AI does not need these
    "role clarity": "Role Clarity & Meaningful Work", "meaningful work": "Role Clarity & Meaningful Work",
    "workload": "Workload & Wellbeing", "wellbeing": "Workload & Wellbeing", "well-being": "Workload & Wellbeing",
    "manager": "Manager Effectiveness", "learning": "Learning & Growth", "career": "Career Development",
    "leadership": "Leadership & Trust", "trust": "Leadership & Trust", "innovation": "Innovation & AI Readiness",
    "ai readiness": "Innovation & AI Readiness", "culture": "Culture & Inclusion", "inclusion": "Culture & Inclusion",
    "communication": "Communication & Change", "organizational health": "Organizational Health",
    "organisational health": "Organizational Health",
}
_NEGATION = r"(?:except|excluding|other than|not in|outside)\s+"


def _month_range(month: int, today: date) -> tuple[str, str]:
    year = today.year if month >= today.month else today.year + 1
    return date(year, month, 1).isoformat(), date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def _match_values(text: str, key: str) -> tuple[list[str], list[str]]:
    """Known values found in text, split into (included, excluded)."""
    inc, exc = [], []
    for v in cfg.KNOWN_VALUES.get(key, []):
        m = re.search(rf"\b{re.escape(v.lower())}\b", text)
        if m:
            negated = re.search(rf"{_NEGATION}(?:[\w&,\s]*?)$", text[:m.start()][-40:])
            (exc if negated else inc).append(v)
    return inc, exc


def mock_generate(rule_text: str, today: date) -> dict:
    text = rule_text.lower()
    spec: dict = {"conditions": [], "themes": [], "question_ids": [], "assumptions": [],
                  "priority": 1, "trigger_frequency": None, "effective_from": None,
                  "effective_to": None, "needs_clarification": None}

    themes = [t for t in cfg.KNOWN_VALUES["theme"] if t.lower() in text]
    themes += [t for alias, t in _THEME_ALIASES.items() if re.search(rf"\b{alias}\b", text)]
    spec["themes"] = list(dict.fromkeys(themes))
    spec["question_ids"] = [int(n) for n in re.findall(r"\bquestion(?:\s*id)?s?\s*#?(\d+)", text)]

    months = [i for i in range(1, 13) if re.search(rf"\b{calendar.month_name[i].lower()}\b", text)]
    if months:
        spec["effective_from"], spec["effective_to"] = _month_range(months[0], today)
        spec["trigger_frequency"] = "Monthly"
        if not spec["themes"] and not spec["question_ids"]:
            spec["needs_clarification"] = "Which theme or questions should be sent?"

    grade = re.search(r"\bg(\d+)\s*(?:and|or)\s*(above|higher|below|lower)\b", text)
    grade_cmp = re.search(r"\b(above|higher than|greater than|below|lower than|less than)\s+g(\d+)\b", text)
    if grade:
        op = ">=" if grade.group(2) in ("above", "higher") else "<="
        spec["conditions"].append({"attribute": cfg.name("employee", "grade"), "operator": op, "value": f"G{grade.group(1)}"})
    elif grade_cmp:
        op = ">" if grade_cmp.group(1) in ("above", "higher than", "greater than") else "<"
        spec["conditions"].append({"attribute": cfg.name("employee", "grade"), "operator": op, "value": f"G{grade_cmp.group(2)}"})

    for key in ["grade", "business_unit", "department", "location", "employment_type"]:
        if key == "grade" and (grade or grade_cmp):
            continue
        inc, exc = _match_values(text, key)
        attr = cfg.name("employee", key)
        for vals, single, multi in ((inc, "=", "IN"), (exc, "!=", "NOT IN")):
            if len(vals) == 1:
                spec["conditions"].append({"attribute": attr, "operator": single, "value": vals[0]})
            elif vals:
                spec["conditions"].append({"attribute": attr, "operator": multi, "value": ", ".join(vals)})

    if not spec["themes"] and not spec["question_ids"] and not spec["needs_clarification"]:
        spec["needs_clarification"] = "Which theme or questions should be sent?"
    when = calendar.month_name[months[0]] if months else "Ad hoc"
    spec["rule_name"] = f"{when} - {', '.join(spec['themes']) or 'questions'}"[:200]
    spec["description"] = rule_text.strip()[:500]
    return spec


# --------------------------------------------------------------------------- azure openai
def azure_generate(rule_text: str, today: date) -> dict:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
    version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    body = {
        "messages": [{"role": "system", "content": build_system_prompt(today)},
                     {"role": "user", "content": rule_text}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={version}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "api-key": os.environ["AZURE_OPENAI_API_KEY"]},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        content = json.loads(resp.read())["choices"][0]["message"]["content"]
    return json.loads(content)


PROVIDERS = {"mock": mock_generate, "azure": azure_generate}


def generate(rule_text: str, provider: str, today: date) -> dict:
    spec = PROVIDERS[provider](rule_text, today)
    spec["source_text"] = rule_text
    return spec
