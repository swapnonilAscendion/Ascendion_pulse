/* =====================================================================
   Ascendion Pulse - POC stored procedures
     pulse.usp_PlanLaunch       - Launcher: eligibility, <=2 questions, funnel
     pulse.usp_RecordResponse   - Teams Card: validate responder, split identity from answers
     pulse.usp_SetLaunchStatus  - Expired / Failed handling from the flow
   ===================================================================== */

CREATE OR ALTER PROCEDURE pulse.usp_PlanLaunch
    @CampaignCode NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @BU NVARCHAR(50), @Cooldown INT, @MaxPerRun INT, @Now DATETIME2(0) = SYSUTCDATETIME();

    SELECT @BU = TargetBusinessUnit, @Cooldown = CooldownDays, @MaxPerRun = MaxPerRun
    FROM pulse.Launch_Rules
    WHERE CampaignCode = @CampaignCode AND IsActive = 1;

    IF @MaxPerRun IS NULL
    BEGIN
        INSERT pulse.Process_Audit (ProcName, Detail) VALUES (N'usp_PlanLaunch', N'No active rule for ' + @CampaignCode);
        SELECT CAST(NULL AS UNIQUEIDENTIFIER) AS LaunchId WHERE 1 = 0;                -- Table1: empty
        SELECT N'No active rule' AS Outcome, 0 AS Employees;                           -- Table2: funnel
        RETURN;
    END;

    /* 1. Candidates with an exclusion reason (NULL = eligible) */
    SELECT e.EmployeeId, e.Upn,
           Reason = CASE
               WHEN e.IsActive = 0                                   THEN N'Excluded: inactive'
               WHEN e.Upn IS NULL OR LTRIM(RTRIM(e.Upn)) = N''       THEN N'Excluded: no Teams UPN'
               WHEN EXISTS (SELECT 1 FROM pulse.Launch_Tracking lt
                            WHERE lt.EmployeeId = e.EmployeeId AND lt.Status = N'Sent')
                                                                     THEN N'Excluded: pulse already pending'
               WHEN @Cooldown > 0 AND EXISTS (SELECT 1 FROM pulse.Launch_Tracking lt
                            WHERE lt.EmployeeId = e.EmployeeId AND lt.Status <> N'Failed'
                              AND lt.PlannedAt >= DATEADD(DAY, -@Cooldown, @Now))
                                                                     THEN N'Excluded: cooldown / fatigue limit'
               ELSE NULL END,
           Q1Id = CAST(NULL AS INT), Q2Id = CAST(NULL AS INT), Rnk = CAST(NULL AS INT)
    INTO #cand
    FROM pulse.Employees e
    WHERE @BU IS NULL OR e.BusinessUnit = @BU;

    /* 2. Match at most 2 approved questions: the one this person saw least recently, random tie-break */
    UPDATE c SET
        Q1Id = (SELECT TOP 1 q.QuestionId FROM pulse.Question_Bank q
                WHERE q.Status = N'Approved' AND q.QuestionType = N'SCALE3'
                ORDER BY (SELECT MAX(lt.PlannedAt) FROM pulse.Launch_Tracking lt
                          WHERE lt.EmployeeId = c.EmployeeId AND lt.Q1Id = q.QuestionId), NEWID()),
        Q2Id = (SELECT TOP 1 q.QuestionId FROM pulse.Question_Bank q
                WHERE q.Status = N'Approved' AND q.QuestionType = N'RATING5'
                ORDER BY (SELECT MAX(lt.PlannedAt) FROM pulse.Launch_Tracking lt
                          WHERE lt.EmployeeId = c.EmployeeId AND lt.Q2Id = q.QuestionId), NEWID())
    FROM #cand c
    WHERE c.Reason IS NULL;

    UPDATE #cand SET Reason = N'Excluded: no approved question'
    WHERE Reason IS NULL AND (Q1Id IS NULL OR Q2Id IS NULL);

    /* 3. Cap per run (throttle guard); the rest wait for the next run */
    ;WITH r AS (SELECT Rnk, ROW_NUMBER() OVER (ORDER BY NEWID()) AS n FROM #cand WHERE Reason IS NULL)
    UPDATE r SET Rnk = n;
    UPDATE #cand SET Reason = N'Deferred: over per-run cap' WHERE Reason IS NULL AND Rnk > @MaxPerRun;

    /* 4. Record launches */
    DECLARE @launched TABLE (LaunchId UNIQUEIDENTIFIER, EmployeeId NVARCHAR(20), Q1Id INT, Q2Id INT);

    INSERT pulse.Launch_Tracking (CampaignCode, EmployeeId, Q1Id, Q2Id, Status)
    OUTPUT inserted.LaunchId, inserted.EmployeeId, inserted.Q1Id, inserted.Q2Id INTO @launched
    SELECT @CampaignCode, EmployeeId, Q1Id, Q2Id, N'Sent'
    FROM #cand WHERE Reason IS NULL;

    /* Table1: one row per card to send. *Json columns are pre-escaped for pasting inside JSON strings. */
    SELECT l.LaunchId,
           e.Upn,
           q1.Theme                                   AS Q1Theme,
           STRING_ESCAPE(q1.QuestionText, 'json')     AS Q1TextJson,
           STRING_ESCAPE(ISNULL(q1.FollowUpText, N'Anything you would like to add? (optional)'), 'json') AS FollowUpTextJson,
           STRING_ESCAPE(q2.QuestionText, 'json')     AS Q2TextJson
    FROM @launched l
    JOIN pulse.Employees     e  ON e.EmployeeId  = l.EmployeeId
    JOIN pulse.Question_Bank q1 ON q1.QuestionId = l.Q1Id
    JOIN pulse.Question_Bank q2 ON q2.QuestionId = l.Q2Id;

    /* Table2: launch funnel - who was left out and why */
    SELECT ISNULL(Reason, N'Planned') AS Outcome, COUNT(*) AS Employees
    FROM #cand GROUP BY ISNULL(Reason, N'Planned');

    INSERT pulse.Process_Audit (ProcName, Detail)
    SELECT N'usp_PlanLaunch', CONCAT(@CampaignCode, N': planned ', COUNT(*)) FROM @launched;
END;
GO

CREATE OR ALTER PROCEDURE pulse.usp_RecordResponse
    @LaunchId      UNIQUEIDENTIFIER,
    @ResponderUpn  NVARCHAR(256),
    @Action        NVARCHAR(10),           -- 'submit' | 'skip'
    @Q1Answer      NVARCHAR(30)  = NULL,
    @Q2Answer      NVARCHAR(5)   = NULL,   -- arrives as text from the card
    @FollowUpText  NVARCHAR(500) = NULL,
    @HrFollowup    NVARCHAR(5)   = NULL    -- 'true' | 'false'
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @EmployeeId NVARCHAR(20), @Upn NVARCHAR(256), @BU NVARCHAR(50),
            @Campaign NVARCHAR(30), @Q1Id INT, @Q2Id INT, @Result NVARCHAR(20);

    BEGIN TRAN;

    SELECT @EmployeeId = lt.EmployeeId, @Upn = e.Upn, @BU = e.BusinessUnit,
           @Campaign = lt.CampaignCode, @Q1Id = lt.Q1Id, @Q2Id = lt.Q2Id
    FROM pulse.Launch_Tracking lt WITH (UPDLOCK, HOLDLOCK)
    JOIN pulse.Employees e ON e.EmployeeId = lt.EmployeeId
    WHERE lt.LaunchId = @LaunchId AND lt.Status = N'Sent';

    IF @EmployeeId IS NULL
        SET @Result = N'Ignored';                                  -- unknown or already closed (idempotent retry)
    ELSE IF LOWER(@Upn) <> LOWER(LTRIM(RTRIM(@ResponderUpn)))
        SET @Result = N'Rejected';                                 -- responder is not the person it was sent to
    ELSE IF @Action = N'skip'
    BEGIN
        UPDATE pulse.Launch_Tracking SET Status = N'Skipped', ClosedAt = SYSUTCDATETIME() WHERE LaunchId = @LaunchId;
        SET @Result = N'Skipped';
    END
    ELSE IF @Q1Answer IS NULL
         OR @Q1Answer NOT IN (N'Manageable', N'Sometimes heavy', N'Overwhelming')
         OR TRY_CAST(@Q2Answer AS TINYINT) IS NULL
         OR TRY_CAST(@Q2Answer AS TINYINT) NOT BETWEEN 1 AND 5
        SET @Result = N'Invalid';
    ELSE
    BEGIN
        /* Answers: no EmployeeId, no LaunchId, date only */
        INSERT pulse.Listen_Response (CampaignCode, ResponseDate, BusinessUnit, Q1Id, Q1Answer, Q2Id, Q2Answer, FollowUpText)
        VALUES (@Campaign, CAST(SYSUTCDATETIME() AS DATE), @BU, @Q1Id, @Q1Answer, @Q2Id,
                TRY_CAST(@Q2Answer AS TINYINT), NULLIF(LTRIM(RTRIM(@FollowUpText)), N''));

        /* Consent-based follow-up: identity only, never the answers */
        IF @HrFollowup = N'true'
            INSERT pulse.HR_Followup (EmployeeId, CampaignCode, RequestedOn)
            VALUES (@EmployeeId, @Campaign, CAST(SYSUTCDATETIME() AS DATE));

        UPDATE pulse.Launch_Tracking SET Status = N'Completed', ClosedAt = SYSUTCDATETIME() WHERE LaunchId = @LaunchId;
        SET @Result = N'Completed';
    END;

    INSERT pulse.Process_Audit (ProcName, Detail)
    VALUES (N'usp_RecordResponse', CONCAT(N'Launch ', @LaunchId, N': ', @Result));   -- never log answers

    COMMIT;

    SELECT @Result AS Result;
END;
GO

CREATE OR ALTER PROCEDURE pulse.usp_SetLaunchStatus
    @LaunchId UNIQUEIDENTIFIER,
    @Status   NVARCHAR(12),            -- 'Expired' | 'Failed'
    @Reason   NVARCHAR(200) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @Status NOT IN (N'Expired', N'Failed') THROW 50001, 'Status must be Expired or Failed.', 1;

    UPDATE pulse.Launch_Tracking
    SET Status = @Status, StatusReason = LEFT(@Reason, 200), ClosedAt = SYSUTCDATETIME()
    WHERE LaunchId = @LaunchId AND Status = N'Sent';           -- only open launches

    DECLARE @Rows INT = @@ROWCOUNT;

    INSERT pulse.Process_Audit (ProcName, Detail)
    VALUES (N'usp_SetLaunchStatus', CONCAT(N'Launch ', @LaunchId, N': ', @Status, N' - ', LEFT(@Reason, 200)));

    SELECT @Rows AS RowsUpdated;
END;
GO
