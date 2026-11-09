/* =====================================================================
   Ascendion Pulse - POC schema (Launcher + Teams Card only)
   Target : Azure SQL Database (a dedicated DEV/POC database)
   Safe to re-run: objects are created only if they do not exist.
   Subset of the 8-table design: Employees, Question_Bank, Launch_Rules,
   Launch_Tracking, Listen_Response, HR_Followup, Process_Audit.
   ===================================================================== */

IF SCHEMA_ID(N'pulse') IS NULL EXEC(N'CREATE SCHEMA pulse');
GO

/* Employee master (in the real build: synced from HCM by Flow 1) */
IF OBJECT_ID(N'pulse.Employees') IS NULL
CREATE TABLE pulse.Employees (
    EmployeeId      NVARCHAR(20)   NOT NULL PRIMARY KEY,
    DisplayName     NVARCHAR(100)  NOT NULL,
    Upn             NVARCHAR(256)  NULL,          -- Entra UPN = the Teams recipient ("Teams ID")
    BusinessUnit    NVARCHAR(50)   NOT NULL,
    Location        NVARCHAR(50)   NOT NULL,
    Grade           NVARCHAR(10)   NOT NULL,
    IsActive        BIT            NOT NULL DEFAULT 1
);
GO

/* Question bank (in the real build: managed by the Power Apps Question Manager) */
IF OBJECT_ID(N'pulse.Question_Bank') IS NULL
CREATE TABLE pulse.Question_Bank (
    QuestionId      INT IDENTITY(1,1) PRIMARY KEY,
    Theme           NVARCHAR(50)   NOT NULL,
    QuestionType    NVARCHAR(10)   NOT NULL,      -- 'SCALE3' (Q1, button-driven) | 'RATING5' (Q2)
    QuestionText    NVARCHAR(300)  NOT NULL,
    FollowUpText    NVARCHAR(300)  NULL,          -- branch question shown on the negative answer (SCALE3 only)
    IsAnonymous     BIT            NOT NULL DEFAULT 1,
    Status          NVARCHAR(10)   NOT NULL DEFAULT N'Approved',  -- Draft | Approved | Retired
    Version         INT            NOT NULL DEFAULT 1,
    CONSTRAINT CK_QB_Type   CHECK (QuestionType IN (N'SCALE3', N'RATING5')),
    CONSTRAINT CK_QB_Status CHECK (Status IN (N'Draft', N'Approved', N'Retired'))
);
GO

/* Launch rules (in the real build: managed by the Power Apps Rules Manager) */
IF OBJECT_ID(N'pulse.Launch_Rules') IS NULL
CREATE TABLE pulse.Launch_Rules (
    RuleId              INT IDENTITY(1,1) PRIMARY KEY,
    CampaignCode        NVARCHAR(30)  NOT NULL UNIQUE,
    TargetBusinessUnit  NVARCHAR(50)  NULL,       -- NULL = all BUs
    CooldownDays        INT           NOT NULL DEFAULT 7,   -- fatigue limit: min days between pulses per person
    MaxPerRun           INT           NOT NULL DEFAULT 20,  -- keep under Flow bot throttle (25 posts / 5 min / connection)
    IsActive            BIT           NOT NULL DEFAULT 1
);
GO

/* Who was asked what, and status. Knows the employee - never holds answers. */
IF OBJECT_ID(N'pulse.Launch_Tracking') IS NULL
CREATE TABLE pulse.Launch_Tracking (
    LaunchId        UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
    CampaignCode    NVARCHAR(30)     NOT NULL,
    EmployeeId      NVARCHAR(20)     NOT NULL REFERENCES pulse.Employees(EmployeeId),
    Q1Id            INT              NOT NULL REFERENCES pulse.Question_Bank(QuestionId),
    Q2Id            INT              NOT NULL REFERENCES pulse.Question_Bank(QuestionId),
    Status          NVARCHAR(12)     NOT NULL DEFAULT N'Sent',
    StatusReason    NVARCHAR(200)    NULL,
    PlannedAt       DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    ClosedAt        DATETIME2(0)     NULL,
    CONSTRAINT CK_LT_Status CHECK (Status IN (N'Sent', N'Completed', N'Skipped', N'Expired', N'Failed'))
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_LT_Employee')
    CREATE INDEX IX_LT_Employee ON pulse.Launch_Tracking (EmployeeId, PlannedAt);
GO

/* Answers. Deliberately NO EmployeeId and NO LaunchId; date only (no time) to block timestamp joins.
   Random GUID key (not IDENTITY): a sequential id would mirror completion order in Launch_Tracking. */
IF OBJECT_ID(N'pulse.Listen_Response') IS NULL
CREATE TABLE pulse.Listen_Response (
    ResponseId      UNIQUEIDENTIFIER NOT NULL PRIMARY KEY NONCLUSTERED DEFAULT NEWID(),
    CampaignCode    NVARCHAR(30)   NOT NULL,
    ResponseDate    DATE           NOT NULL,
    BusinessUnit    NVARCHAR(50)   NOT NULL,      -- reporting segment; N >= 8 enforced at reporting time
    Q1Id            INT            NOT NULL,
    Q1Answer        NVARCHAR(30)   NOT NULL,
    Q2Id            INT            NOT NULL,
    Q2Answer        TINYINT        NULL,
    FollowUpText    NVARCHAR(500)  NULL
);
GO

/* Identifiable by explicit employee consent. Holds the request, NOT the answers. */
IF OBJECT_ID(N'pulse.HR_Followup') IS NULL
CREATE TABLE pulse.HR_Followup (
    FollowupId      INT IDENTITY(1,1) PRIMARY KEY,
    EmployeeId      NVARCHAR(20)   NOT NULL REFERENCES pulse.Employees(EmployeeId),
    CampaignCode    NVARCHAR(30)   NOT NULL,
    RequestedOn     DATE           NOT NULL,
    Status          NVARCHAR(12)   NOT NULL DEFAULT N'Open'
);
GO

IF OBJECT_ID(N'pulse.Process_Audit') IS NULL
CREATE TABLE pulse.Process_Audit (
    AuditId         BIGINT IDENTITY(1,1) PRIMARY KEY,
    EventTime       DATETIME2(0)   NOT NULL DEFAULT SYSUTCDATETIME(),
    ProcName        NVARCHAR(100)  NOT NULL,
    Detail          NVARCHAR(1000) NULL
);
GO
