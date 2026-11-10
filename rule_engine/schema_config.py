"""
Single source of truth for the Pulse database schema.
Source: "Glossary 2.xlsx" -> sheet "Final Version" (proposed revised data model, 9 tables).

No other file hard-codes a table or column name. Code asks for names by LOGICAL KEY:
    T("rule")                -> [dbo].[Rule]
    C("employee", "grade")   -> [Grade]
When the glossary changes:
    * column / table renamed   -> change the physical name string below, nothing else
    * new column               -> add one Col(...) line
    * proposed column agreed   -> remove proposed=True;  dropped -> delete the line
    * status / operator lists  -> edit the lists at the bottom
Then regenerate the DDL:  python main.py ddl
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- placeholders
DB_SCHEMA = "dbo"           # TODO: confirm once DB access is granted (dbo / pulse)
INCLUDE_PROPOSED = True     # False = emit only columns that are in the glossary today


@dataclass(frozen=True)
class Col:
    name: str                               # physical column name
    type: str                               # SQL Server type, without IDENTITY
    nullable: bool = True
    pk: bool = False
    identity: bool = False
    unique: bool = False
    default: str | None = None              # raw SQL default expression
    fk: tuple[str, str] | None = None       # (table_key, column_key)
    desc: str = ""
    proposed: bool = False                  # not in the glossary yet - our suggestion


@dataclass
class Table:
    name: str                               # physical table name
    columns: dict[str, Col]
    desc: str = ""
    checks: list[str] = field(default_factory=list)                     # {column_key} placeholders
    unique_together: list[tuple[str, ...]] = field(default_factory=list)


# --------------------------------------------------------------------------- tables (FK order)
TABLES: dict[str, Table] = {
    "employee": Table("Employee", desc="Employee master data from HCM, incl. reporting hierarchy.", columns={
        "id":              Col("EmployeeID", "NVARCHAR(50)", nullable=False, pk=True, desc="Unique employee identifier received from HCM."),
        "name":            Col("EmployeeName", "NVARCHAR(200)", nullable=False, desc="Full name of the employee."),
        "email":           Col("EmployeeEmail", "NVARCHAR(255)", nullable=False, unique=True, desc="Corporate email address (also the Teams recipient)."),
        "manager_id":      Col("ManagerEmployeeID", "NVARCHAR(50)", fk=("employee", "id"), desc="Employee ID of the reporting manager."),
        "business_unit":   Col("BusinessUnit", "NVARCHAR(100)", desc="Business unit, e.g. Finance, Sales, Technology."),
        "department":      Col("Department", "NVARCHAR(100)", desc="Employee department or function."),
        "location":        Col("Location", "NVARCHAR(100)", desc="Assigned work location."),
        "grade":           Col("Grade", "NVARCHAR(50)", desc="Employee grade used for rule evaluation, e.g. G5."),
        "date_of_joining": Col("DateOfJoining", "DATE", desc="Employee joining date."),
        "employment_type": Col("EmploymentType", "NVARCHAR(50)", desc="Employment category, e.g. Permanent or Contract."),
        "hrbp":            Col("HRBP", "NVARCHAR(200)", desc="HR business partner associated with the employee."),
        "cost_center":     Col("CostCenter", "NVARCHAR(50)", desc="Employee cost centre."),
        "legal_entity":    Col("LegalEntity", "NVARCHAR(100)", desc="Legal employing entity."),
        "is_active":       Col("IsActive", "BIT", nullable=False, default="1", desc="Whether the employee is active."),
    }),

    "theme": Table("Theme", desc="Themes used to classify questions.", columns={
        "id":          Col("ThemeID", "INT", nullable=False, pk=True, identity=True, desc="Unique theme identifier."),
        "name":        Col("ThemeName", "NVARCHAR(100)", nullable=False, unique=True, desc="Business name of the theme, e.g. Leadership, Wellbeing."),
        "description": Col("Description", "NVARCHAR(500)", desc="Description of the theme."),
        "is_active":   Col("IsActive", "BIT", nullable=False, default="1", desc="Whether the theme is available for use."),
    }),

    "event_classification": Table("EventClassification", desc="Event / lifecycle classifications for questions.", columns={
        "id":          Col("EventClassificationID", "INT", nullable=False, pk=True, identity=True, desc="Unique event classification identifier."),
        "name":        Col("ClassificationName", "NVARCHAR(100)", nullable=False, unique=True, desc="e.g. Quarterly Check-in, New Joiner."),
        "description": Col("Description", "NVARCHAR(500)", desc="When the classification applies."),
        "is_active":   Col("IsActive", "BIT", nullable=False, default="1", desc="Whether the classification is active."),
    }),

    "question": Table("QuestionBank", desc="Master list of questions available for assignment.", checks=["{version} >= 1"], columns={
        "id":                      Col("QuestionID", "BIGINT", nullable=False, pk=True, identity=True, desc="Unique question identifier."),
        "text":                    Col("QuestionText", "NVARCHAR(1000)", nullable=False, desc="Question presented to the employee."),
        "theme_id":                Col("ThemeID", "INT", nullable=False, fk=("theme", "id"), desc="Theme under which the question is classified."),
        "grade":                   Col("Grade", "NVARCHAR(50)", desc="Employee grade the question is intended for (NULL = any)."),
        "event_classification_id": Col("EventClassificationID", "INT", fk=("event_classification", "id"), desc="Associated lifecycle classification."),
        "anonymization_required":  Col("AnonymizationRequired", "BIT", nullable=False, default="0", desc="Whether responses must be anonymized."),
        "approval_status":         Col("ApprovalStatus", "NVARCHAR(30)", nullable=False, default="N'Draft'", desc="Question approval status."),
        "version":                 Col("VersionNumber", "INT", nullable=False, default="1", desc="Question version; at least 1."),
        "is_active":               Col("IsActive", "BIT", nullable=False, default="1", desc="Whether the question is available for use."),
        # Proposed: HR question bank columns D, F, G (Pandian, stand-up 09-Nov: "store B to G").
        "category":                Col("QuestionCategory", "NVARCHAR(50)", proposed=True, desc="e.g. Agreement Statement, Open Text."),
        "answer_format":           Col("AnswerFormat", "NVARCHAR(100)", proposed=True, desc="e.g. 1-10 Rating (emoji scale), Short free text."),
        "ui_treatment":            Col("UITreatment", "NVARCHAR(1000)", proposed=True, desc="Card rendering hint for the Teams card team."),
    }),

    "rule": Table(
        "Rule",  # NOTE: RULE is a reserved word in T-SQL - always use the bracketed T("rule").
        desc="Business rules that determine employee eligibility for question assignment.",
        checks=[
            "{priority} >= 1",
            "{effective_to} IS NULL OR {effective_from} IS NULL OR {effective_to} >= {effective_from}",
            "{status} IN ({RULE_STATUSES})",
        ],
        columns={
            "id":                Col("RuleID", "BIGINT", nullable=False, pk=True, identity=True, desc="Unique rule identifier."),
            "name":              Col("RuleName", "NVARCHAR(200)", nullable=False, desc="Business-friendly rule name."),
            "description":       Col("Description", "NVARCHAR(500)", desc="Description of the rule."),
            "trigger_frequency": Col("TriggerFrequency", "NVARCHAR(50)", desc="Evaluation frequency, e.g. Daily, Weekly, Monthly."),
            "effective_from":    Col("EffectiveFrom", "DATE", desc="Date from which the rule is effective."),
            "effective_to":      Col("EffectiveTo", "DATE", desc="Date on which the rule expires."),
            "priority":          Col("Priority", "INT", nullable=False, default="1", desc="Evaluation priority; at least 1."),
            "is_active":         Col("IsActive", "BIT", nullable=False, default="1", desc="Whether the rule is active."),
            "created_at":        Col("CreatedAt", "DATETIME2", nullable=False, default="SYSUTCDATETIME()", desc="Rule creation timestamp."),
            "updated_at":        Col("UpdatedAt", "DATETIME2", desc="Last modification timestamp."),
            # Proposed: Rules Manager lifecycle (Pandian, stand-up 09-Nov: Draft -> Tested -> Approved).
            "status":            Col("RuleStatus", "NVARCHAR(20)", nullable=False, default="N'Draft'", proposed=True, desc="Draft / Tested / Approved / Retired."),
            "source_text":       Col("RuleTextEnglish", "NVARCHAR(1000)", proposed=True, desc="The plain-English rule HR typed."),
            "created_by":        Col("CreatedBy", "NVARCHAR(255)", proposed=True, desc="HR user who created the rule."),
            "approved_by":       Col("ApprovedBy", "NVARCHAR(255)", proposed=True, desc="HR user who approved the rule."),
            "approved_at":       Col("ApprovedAt", "DATETIME2", proposed=True, desc="Approval timestamp."),
        },
    ),

    "rule_condition": Table("RuleCondition", desc="Conditions an employee must meet for a rule (all ANDed).", columns={
        "id":        Col("RuleConditionID", "BIGINT", nullable=False, pk=True, identity=True, desc="Unique rule condition identifier."),
        "rule_id":   Col("RuleID", "BIGINT", nullable=False, fk=("rule", "id"), desc="Parent rule."),
        "attribute": Col("AttributeName", "NVARCHAR(100)", nullable=False, desc="Employee attribute to evaluate, e.g. Grade, Department."),
        "operator":  Col("Operator", "NVARCHAR(20)", nullable=False, desc="Comparison operator, e.g. =, !=, >, <, IN."),
        "value":     Col("AttributeValue", "NVARCHAR(500)", nullable=False, desc="Value to compare against; comma-separated for IN."),
    }),

    "rule_question": Table("RuleQuestion", desc="Maps rules to the questions sent when the rule is satisfied.",
        unique_together=[("rule_id", "question_id")], columns={
        "id":          Col("RuleQuestionID", "BIGINT", nullable=False, pk=True, identity=True, desc="Unique rule-question mapping identifier."),
        "rule_id":     Col("RuleID", "BIGINT", nullable=False, fk=("rule", "id"), desc="Rule associated with the question."),
        "question_id": Col("QuestionID", "BIGINT", nullable=False, fk=("question", "id"), desc="Question associated with the rule."),
        "is_active":   Col("IsActive", "BIT", nullable=False, default="1", desc="Whether the mapping is active."),
        "sequence":    Col("SequenceNo", "INT", nullable=False, desc="Order in which the questions are sent."),
        "created_at":  Col("CreatedAt", "DATETIME2", nullable=False, default="SYSUTCDATETIME()", desc="Mapping creation timestamp."),
    }),

    "assignment": Table("EmployeeQuestionAssignment", desc="Questions assigned to employees from a rule-question mapping.",
        checks=["{status} IN ({ASSIGNMENT_STATUSES})"], columns={
        "id":               Col("AssignmentID", "BIGINT", nullable=False, pk=True, identity=True, desc="Unique assignment identifier."),
        "employee_id":      Col("EmployeeID", "NVARCHAR(50)", nullable=False, fk=("employee", "id"), desc="Employee receiving the question."),
        "rule_question_id": Col("RuleQuestionID", "BIGINT", nullable=False, fk=("rule_question", "id"), desc="Mapping that generated the assignment."),
        "assigned_at":      Col("AssignedAt", "DATETIME2", nullable=False, default="SYSUTCDATETIME()", desc="Date and time of assignment."),
        "due_date":         Col("DueDate", "DATETIME2", desc="Expected completion date."),
        "status":           Col("AssignmentStatus", "NVARCHAR(30)", nullable=False, default="N'Assigned'", desc="See ASSIGNMENT_STATUSES."),
    }),

    "response": Table("EmployeeQuestionResponse", desc="Responses submitted against assignments.",
        checks=["{status} IN ({RESPONSE_STATUSES})"], columns={
        "id":            Col("ResponseID", "BIGINT", nullable=False, pk=True, identity=True, desc="Unique response identifier."),
        "assignment_id": Col("AssignmentID", "BIGINT", nullable=False, fk=("assignment", "id"), desc="Assignment the response is for."),
        "response_text": Col("ResponseText", "NVARCHAR(MAX)", desc="Employee's submitted response."),
        "submitted_at":  Col("SubmittedAt", "DATETIME2", desc="Date and time of submission."),
        "status":        Col("ResponseStatus", "NVARCHAR(30)", nullable=False, default="N'Draft'", desc="Draft or Submitted."),
        "is_anonymized": Col("IsAnonymized", "BIT", nullable=False, default="0", desc="Whether the stored response has been anonymized."),
    }),
}

# --------------------------------------------------------------------------- value lists
QUESTION_APPROVAL_STATUSES = ["Draft", "Approved", "Rejected"]
RULE_STATUSES = ["Draft", "Tested", "Approved", "Retired"]
# Glossary: "Assigned, Completed, Cancelled or Expired (include reminders count) - rem-1".
# TODO: confirm with Sharmilee whether reminders are statuses (below) or a separate count column.
ASSIGNMENT_STATUSES = ["Assigned", "REM-1", "REM-2", "Completed", "Cancelled", "Expired"]
RESPONSE_STATUSES = ["Draft", "Submitted"]
TRIGGER_FREQUENCIES = ["Once", "Daily", "Weekly", "Monthly"]

# --------------------------------------------------------------------------- rule engine settings
# Employee columns HR rules may filter on (logical keys). Identity columns are deliberately excluded.
CONDITION_ATTRIBUTES = ["business_unit", "department", "location", "grade", "employment_type",
                        "legal_entity", "cost_center", "date_of_joining", "manager_id", "hrbp"]
OPERATORS = ["=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN"]
LIST_OPERATORS = {"IN", "NOT IN"}
LIST_SEPARATOR = ","                    # how IN values are packed into AttributeValue
GRADE_PREFIX = "G"                      # G5 -> 5, so "> G5" compares numbers, not strings ('G10' < 'G5')
PREVIEW_TOP = 50

# Reference values shown to the AI so it maps "culture" to an exact ThemeName.
# TODO: replace with SELECT DISTINCT ... from the DB once access is granted.
KNOWN_VALUES: dict[str, list[str]] = {
    "theme": [
        "Role Clarity & Meaningful Work", "Workload & Wellbeing", "Manager Effectiveness", "Collaboration",
        "Recognition", "Communication & Change", "Learning & Growth", "Career Development",
        "Leadership & Trust", "Innovation & AI Readiness", "Culture & Inclusion", "Organizational Health",
    ],
    "grade": [f"G{n}" for n in range(1, 13)],
    "business_unit": ["Technology", "Finance", "Sales"],
    "department": ["Engineering", "Data", "D&I"],
    "location": ["Chennai", "Bengaluru", "Hyderabad", "Pune"],
    "employment_type": ["Permanent", "Contract"],
}


# --------------------------------------------------------------------------- name helpers
def columns(table_key: str) -> dict[str, Col]:
    """Columns of a table, honouring INCLUDE_PROPOSED."""
    return {k: c for k, c in TABLES[table_key].columns.items() if INCLUDE_PROPOSED or not c.proposed}


def has(table_key: str, col_key: str) -> bool:
    return col_key in columns(table_key)


def name(table_key: str, col_key: str) -> str:
    """Unquoted physical column name, e.g. 'Grade' (for storing in RuleCondition.AttributeName)."""
    return columns(table_key)[col_key].name


def T(table_key: str) -> str:
    return f"[{DB_SCHEMA}].[{TABLES[table_key].name}]"


def C(table_key: str, col_key: str) -> str:
    return f"[{name(table_key, col_key)}]"


def condition_attributes() -> dict[str, str]:
    """Physical attribute name -> logical key, for the attributes rules may use."""
    return {name("employee", k): k for k in CONDITION_ATTRIBUTES if has("employee", k)}


def sql_list(values: list[str]) -> str:
    return ", ".join("N'" + v.replace("'", "''") + "'" for v in values)


VALUE_LISTS = {
    "QUESTION_APPROVAL_STATUSES": QUESTION_APPROVAL_STATUSES,
    "RULE_STATUSES": RULE_STATUSES,
    "ASSIGNMENT_STATUSES": ASSIGNMENT_STATUSES,
    "RESPONSE_STATUSES": RESPONSE_STATUSES,
}
