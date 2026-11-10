# Rules Manager engine

Turns an HR rule written in plain English into SQL for the `Rule`, `RuleCondition` and `RuleQuestion` tables.
The schema comes from `Glossary 2.xlsx` → "Final Version". The engine uses only the Python standard library (3.10+).

```
English rule ──► AI (mock | azure | paste prompt elsewhere) ──► RuleSpec JSON
            ──► validate (allow-listed attributes / operators / themes)
            ──► Preview SQL (read-only, HR checks who gets what)
            ──► Insert SQL (Rule + RuleCondition + RuleQuestion, one transaction)
```

The AI never writes SQL. It only fills in a JSON spec. The SQL is built from that spec using fixed templates, and every table and column name comes from `schema_config.py`.

## When the schema changes
Edit **only** `schema_config.py`, then run `python main.py ddl`.

| Change | Where |
|---|---|
| Table or column renamed | The name string in `TABLES` |
| Column added or removed | Add or delete one `Col(...)` line |
| Proposed column agreed or dropped | Remove `proposed=True`, or delete the line. `INCLUDE_PROPOSED = False` hides all proposed columns |
| Status lists, operators, which attributes rules may use | The lists at the bottom of the file |
| Schema name (`dbo` / `pulse`) | `DB_SCHEMA` |
| Theme / location / grade lists given to the AI | `KNOWN_VALUES` (later: load from the DB) |

If you rename a column used in `eval_cases.json` (for example `Grade`), update the expected `attribute` values there too.

## Commands
```
python main.py ddl                                    # writes rule_engine/sql/01_schema.sql
python main.py prompt                                 # AI system prompt, to paste into AI Builder / Copilot Studio
python main.py rule "Workload questions to G5 in Chennai for December"
python main.py rule "..." --provider azure            # needs AZURE_OPENAI_ENDPOINT / _API_KEY / _DEPLOYMENT
python main.py rule --spec-file out.json              # JSON returned by another AI tool
python main.py eval --provider mock -v                # score a provider on eval_cases.json
```

## Open points (glossary vs. stand-up)
- `Rule` has no status column. The Draft → Tested → Approved workflow needs `RuleStatus` (proposed).
- `QuestionBank` has no category, answer format or UI treatment columns, but HR's question bank has them (proposed).
- Reminders: are they assignment statuses (`REM-1`, `REM-2`) or a count column?
- `EmployeeQuestionResponse` → `AssignmentID` → `EmployeeID` links every answer to a person. This conflicts with the architecture decision that answers carry no EmployeeID.
- `RULE` is a reserved word in T-SQL. Every query must use `[Rule]` (the builder already does).
