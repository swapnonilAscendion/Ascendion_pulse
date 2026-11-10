# Ascendion Pulse – handoff and project context

**Read this first.** Swapnonil (the user) moved from a personal laptop to an office laptop on 2026-11-10. The earlier Claude session's memory did not come along. Everything it learned is written here. Pronouns for team members are not known, so use they/them.

## 1. What the project is
Ascendion Pulse is an internal employee-listening platform for Ascendion HR, similar to Infeedo.
- Employees get short check-ins in **Microsoft Teams** as Adaptive Cards, at most 2 questions at a time, with branching.
- AI analyses the answers for sentiment and themes.
- HR and managers act on the results. A human always approves; the AI only recommends.

**Stack:**

| Layer | Technology | Pieces |
|---|---|---|
| Admin UI | Power Apps | Question Manager, Rules Manager |
| Automation | Power Automate | 8 flows: Sync, Launch, Teams delivery, Reminder, Collector, AI, Recommender, SLA |
| Data | **Azure SQL** | Primary store. Dataverse only packages the flows |
| AI (proposed, NOT licensed yet) | Azure OpenAI, AI Language, Copilot Studio | |
| Reporting | Power BI | Reports hidden for groups smaller than 8 (N ≥ 8) |
| Tickets | ServiceNow | |

**Key principles:**
- Answers should not carry an EmployeeID. Launch tracking and responses are kept separate.
- Personal details are masked before any text is sent to an AI model.
- Every run is audited, and flows are idempotent.

## 2. Files in this repo
| File | What it is |
|---|---|
| `Ascendion Employee  Listening Organisation - BRD + MVP V 1.0.docx` | Business requirements. "Red" rows = Phase-1 must-haves missing from the BRD: question admin CRUD, ≤2 questions per card, branching follow-up, staggered timing, admin dashboard (sent / responded / pending / %), closure summary, mobile, N ≥ 8, pilot with 1–2 teams in India |
| `Ascendion_Pulse_Architecture (1).pptx`, `PulseSolutionBlocks.pptx` | Architecture: 7–8 tables, 8 flows, 5 AI capabilities, AI rollout in phases |
| `Question Bank - VOA Pulse Theme based Survey.xlsx` | HR's question bank. One theme per month, 4 questions each (see below) |
| `Daily stand up _ Listening Organization Project .docx` | Stand-up transcript, 2026-11-09 |
| `Glossary 2.xlsx` | DB glossary by Sharmilee. The sheet **"Final Version"** = 9-table model. "Sheet3" = sample joined rows |
| `poc/` | User's earlier Teams-card POC (Stage A static card, Stage B launcher with its own `pulse.*` schema). **Its schema is outdated.** The card JSON and flow steps are still useful |
| `rule_engine/`, `main.py` | Rules Manager engine built on 2026-11-09 (section 5) |
| `tools/inspect_db.ps1` | Read-only DB inspection script, **untested** (section 6) |

**Reading Office files without extra packages:** python-docx and openpyxl are not installed. Unzip the file with Python's `zipfile` and parse the XML with `xml.etree`:
- docx: `word/document.xml`
- pptx: `ppt/slides/slideN.xml`; speaker notes in `ppt/notesSlides/`
- xlsx: `xl/sharedStrings.xml` plus the sheet XML; map sheet names to files through `xl/_rels/workbook.xml.rels`

Call `sys.stdout.reconfigure(encoding="utf-8")` in the script, because the console uses cp1252 and the files contain emoji. `python -I` ignores `PYTHONIOENCODING`.

**Question bank:**
- **Themes, Jan to Dec:** Role Clarity & Meaningful Work · Workload & Wellbeing · Manager Effectiveness · Collaboration · Recognition · Communication & Change · Learning & Growth · Career Development · Leadership & Trust · Innovation & AI Readiness · Culture & Inclusion · Organizational Health.
- **Each month has 4 questions:** 2 agreement statements on a 1–10 emoji scale, 1 visual-metaphor choice, and 1 optional free-text question (140 characters).
- **Columns:** Month, Theme, Q#, Question Category, Question Text, Answer Format, Teams UI Treatment.
- **Gap:** the visual-choice questions have no answer options defined.

## 3. Team and the decisions from the 2026-11-09 stand-up
| Person | Role / work |
|---|---|
| Muneeswara Pandian | Lead |
| Srikanth K | PM, stakeholders, licences |
| Sharmilee Deviprasath | DB model; rule SQL (sequence-based "prequel/sequel" assignment) |
| Ajay Katepogu | Power Automate flow that runs approved rules and writes EmployeeQuestionAssignment; Question Bank CRUD Power App |
| Vidhan, Saraswathi, Anubha | Power Apps UI |
| **Swapnonil** | Teams cards (`poc/`) + **Rules Manager with AI** |

**Decisions:**
- There is one rule per month (month → theme).
- Question-bank columns B–G are stored in QuestionBank. Column G is the card-rendering hint for the card team.
- A rule moves through **Draft → Tested → Approved**. Only approved rules are run by Ajay's flow.
- HR can send a test card to themselves before approving.
- Assignment statuses: Assigned / Completed / Cancelled / Expired. Pandian wants reminder statuses REM-1 and REM-2.

**Blockers:**
- Power Automate / Power Apps **Premium licence**, needed for the SQL connector. It was expected around Wed 2026-11-11.
- **Prototype due by the week ending 2026-11-20.**

## 4. Swapnonil's tasks
1. **Rules Manager (Power Apps):**
   - HR types a rule in plain English, AI interprets it, and HR reviews the result.
   - The screen shows a preview of which employees get which questions, plus the SQL.
   - HR can send a test card to themselves.
   - The rule is saved with a status: Draft → Tested → Approved.
2. **Research:** which AI option is best for turning English into a rule:
   - Azure OpenAI
   - AI Builder prompts (Power Platform native)
   - Copilot Studio
   - Azure AI Language (**has no NL-to-SQL**, only intent and entity extraction; usable only as a template-based fallback)
   - Open source (Vanna, SQLCoder, LangChain)
3. **Teams cards from the DB:** once the licence arrives, read Ajay's assignment table and send the cards.

## 5. What has been built: `rule_engine/` + `main.py` (Python 3.10, standard library only)
**Design decision:** the AI never writes SQL. It returns a JSON **RuleSpec** (themes, conditions, dates). `rule_spec.validate()` checks it against allow-lists for attributes, operators and known themes. `sql_builder` then builds the SQL from templates:
- a **read-only preview** (which employees get which questions, plus counts)
- a **one-transaction insert** into Rule, RuleCondition and RuleQuestion

**Files:**
- `schema_config.py` is the **single source of truth** for every table and column name. Code asks for names by logical key (`T("rule")`, `C("employee","grade")`), so a schema change is a one-line edit.
  - Columns we suggest but that aren't in the glossary are marked `proposed=True`. `INCLUDE_PROPOSED` turns them all on or off.
  - `KNOWN_VALUES` (themes, locations, grades) are placeholders, to be replaced with `SELECT DISTINCT` from the DB.
- `ddl.py` generates `rule_engine/sql/01_schema.sql`. Never edit that file by hand.
- `llm.py` has the AI side:
  - The prompt is built from the config (`python main.py prompt` prints it for pasting into AI Builder or Copilot Studio).
  - The `mock` provider is an offline keyword parser.
  - The `azure` provider calls Azure OpenAI over REST. It reads `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` and optionally `AZURE_OPENAI_API_VERSION`.
- `eval_cases.json` holds 10 sample English rules with expected results. The reference date is 2026-11-09.
- **Commands:** `python main.py ddl | prompt | rule "<text>" [--provider azure] [--spec-file f.json] | eval [-v]`

**Verified:**
- Renaming a column in the config carries through to the DDL and the generated SQL.
- With `INCLUDE_PROPOSED=False`, proposed columns and their checks disappear.
- An injection attempt in a value is escaped as a string literal.
- A disallowed attribute or operator from the AI is rejected.
- **Not verified:**
  - The mock's 10/10 eval score is meaningless: the mock and the cases were written together. Real rules written by HR or Pandian are needed.
  - No generated SQL has been run against SQL Server yet.

**Built-in conventions:**
- `RULE` is a reserved word in T-SQL, so the table is always written `[Rule]`.
- Grade ranges are compared numerically (`TRY_CAST(SUBSTRING(Grade,2,10) AS INT)`), because as text 'G10' < 'G5'.
- `IN` values are stored comma-separated in one field.

**Important:** Power Platform cannot run Python. `rule_engine` is a prototype, an evaluation harness and a reference implementation. For production, the plan was to port `validate` + `sql_builder` to a **T-SQL stored procedure**, `usp_CreateRuleFromSpec @SpecJson`, using `OPENJSON` (the architecture already uses OPENJSON for the employee sync). The flow would be: Power App → Power Automate → AI → stored procedure. The alternative is an Azure Function running the Python.

## 6. Database: current status (2026-11-10)
- The user says the **DB has been updated and access granted**. The service is called **`db-ava-data-poc`**.
- **Schema changes announced by the user:**
  - `EventClassification` and `RuleCondition` are **removed**.
  - "Everything will be under **EmployeeQuestionnaire**". It is not yet clear whether that's a schema name or the database name. Find out.
- On the personal laptop, `db-ava-data-poc.database.windows.net` **did not resolve**, so `db-ava-data-poc` is probably the database name and the server address is something else. Get the server address from the Azure portal (database → Overview → Server name). Check how authentication works (Entra ID vs SQL login) and that the firewall allows this laptop's IP.
- The personal laptop's `az` CLI was signed in with a personal Gmail account. On the office laptop, use `az login` with the Ascendion account.
- **To inspect the database (read-only; never run DML/DDL without the user's explicit OK):**
  ```powershell
  .\tools\inspect_db.ps1 -Server <server>.database.windows.net -Database <db> [-Samples]
  # SQL login instead: $env:PULSE_SQL_PASSWORD='...'; add -Auth SqlLogin -User <user>
  ```
  The script uses the .NET SqlClient built into PowerShell 5.1 with an `az` access token, so nothing needs installing, and writes `tools/db_inspection.md`. It was written blind; only a syntax check has been done. Fix it if it fails. `-Samples` dumps TOP 5 rows per table, which may include employee names and emails, so ask before using it on real data and don't commit the output.

## 7. Next steps, in order
1. **Connect** (section 6) and run the inspection. Report the actual tables, columns, keys and row counts, and compare them with Glossary "Final Version".
2. **Update `schema_config.py` to match the real DB:**
   - remove `event_classification` (and the QuestionBank FK to it)
   - remove `rule_condition`
   - set `DB_SCHEMA`
   - fix renamed or added columns
   - map the proposed columns that now exist
   - replace `KNOWN_VALUES` with real distinct values
3. **Work out where rule conditions live now that RuleCondition is gone.** Possibilities:
   - columns on `Rule` (e.g. Grade, BU, Location)
   - a SQL/filter text column on `Rule` (Pandian's "every rule is a SQL query" idea)
   - something in the new EmployeeQuestionnaire structure

   Then rework `rule_spec` / `sql_builder` (`build_insert_sql` currently inserts RuleCondition rows) and `eval_cases.json`. Ask the user or Sharmilee if the DB doesn't make it clear.
4. Run `python main.py ddl` and diff it against the real DB. Run the generated preview SQL against the DB as read-only SELECTs.
5. **Get access to an AI option.** Try Azure OpenAI or AI Builder, run `python main.py eval --provider azure -v`, and get 10–15 test rules written by HR or Pandian.
6. **Port to the stored procedure** (`usp_CreateRuleFromSpec`, plus preview/validate procedures). Then build the Power Apps screens: rule list, rule editor (English → Generate → explanation + preview + SQL behind a toggle), Test (card to self, reusing `poc/` card flow steps), and Approve (Tested-only, ideally by a different user).
7. **Teams cards from the assignment table**, once the Premium licence is active.

## 8. Open questions for the team (raise with Sharmilee and Pandian)
- Rule needs a status column (Draft / Tested / Approved / Retired) plus the English text, CreatedBy and ApprovedBy. These are proposed in the config.
- QuestionBank needs QuestionCategory, AnswerFormat and UITreatment from HR's Excel (proposed). Visual-choice answer options are not defined anywhere.
- Reminders: are they statuses (REM-1/REM-2) or a count column?
- **Anonymity conflict:** EmployeeQuestionResponse → AssignmentID → EmployeeID links every answer to a person. The architecture says answers carry no EmployeeID.
- The BRD allows ≤2 questions at a time, but each theme has 4 questions. Is that 2 cards in sequence (RuleQuestion.SequenceNo)?
- Ajay's flow needs an agreed output format for a rule (e.g. EmployeeID, QuestionID, SequenceNo).

## 9. Environment and working conventions
- Windows 11, PowerShell 5.1 (no `&&`), Git Bash also available. Python 3.10, standard library only, so far. No `sqlcmd`, no pyodbc. The only ODBC driver is the legacy "SQL Server" one.
- Repo: `https://github.com/swapnonilAscendion/Ascendion_pulse` (branch `master`). Don't commit or push unless asked.
- The user likes short bullet summaries they can paste into the Teams channel.
- Check the latest stand-up transcript or notes, if the user adds one, before assuming the plan above still holds.
