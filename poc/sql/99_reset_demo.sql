/* =====================================================================
   POC ONLY - clears launch history and answers so you can re-test.
   Keeps Employees, Question_Bank and Launch_Rules.
   Do NOT run against any database holding real responses.
   ===================================================================== */
DELETE FROM pulse.Listen_Response;
DELETE FROM pulse.HR_Followup;
DELETE FROM pulse.Launch_Tracking;
INSERT pulse.Process_Audit (ProcName, Detail) VALUES (N'99_reset_demo', N'Demo data reset');
GO

/* Handy checks while testing */
-- SELECT Status, COUNT(*) FROM pulse.Launch_Tracking GROUP BY Status;
-- SELECT * FROM pulse.Listen_Response;
-- SELECT * FROM pulse.HR_Followup;
-- SELECT TOP 50 * FROM pulse.Process_Audit ORDER BY AuditId DESC;
