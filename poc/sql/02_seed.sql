/* =====================================================================
   Ascendion Pulse - POC dummy data
   >>> BEFORE RUNNING: replace the UPNs below with real test accounts
       (yourself / teammates who agreed to test). Rows with Upn = NULL
       are intentionally left out by the planner, to demo the funnel.
   Dummy names only - do not load real HCM data into a POC database.
   ===================================================================== */

IF NOT EXISTS (SELECT 1 FROM pulse.Employees)
INSERT INTO pulse.Employees (EmployeeId, DisplayName, Upn, BusinessUnit, Location, Grade, IsActive) VALUES
 (N'E1001', N'Test User One',   N'test.user1@yourtenant.com', N'Digital Engineering', N'Bengaluru', N'G5', 1),
 (N'E1002', N'Test User Two',   N'test.user2@yourtenant.com', N'Digital Engineering', N'Hyderabad', N'G6', 1),
 (N'E1003', N'Test User Three', N'test.user3@yourtenant.com', N'Digital Engineering', N'Chennai',   N'G4', 1),
 (N'E1004', N'No Teams Account', NULL,                         N'Digital Engineering', N'Pune',      N'G5', 1),  -- left out: no UPN
 (N'E1005', N'Inactive Person', N'inactive@yourtenant.com',   N'Digital Engineering', N'Pune',      N'G5', 0);  -- left out: inactive
GO

IF NOT EXISTS (SELECT 1 FROM pulse.Question_Bank)
INSERT INTO pulse.Question_Bank (Theme, QuestionType, QuestionText, FollowUpText, Status) VALUES
 (N'Workload',        N'SCALE3',  N'How manageable has your workload been this week?',        N'Sorry to hear that. What is adding most to your workload? (optional)', N'Approved'),
 (N'Tools',           N'SCALE3',  N'How well do your tools and access support your work?',   N'What is getting in the way? (optional)',                              N'Approved'),
 (N'Career growth',   N'SCALE3',  N'How do you feel about your learning opportunities lately?', N'What would help you grow? (optional)',                           N'Draft'),   -- not used: Draft
 (N'Manager support', N'RATING5', N'How supported do you feel by your manager? (1 = not at all, 5 = fully)', NULL, N'Approved'),
 (N'Recognition',     N'RATING5', N'How recognised do you feel for your work? (1 = not at all, 5 = fully)',  NULL, N'Approved');
GO

IF NOT EXISTS (SELECT 1 FROM pulse.Launch_Rules)
INSERT INTO pulse.Launch_Rules (CampaignCode, TargetBusinessUnit, CooldownDays, MaxPerRun, IsActive) VALUES
 (N'POC-PULSE-01', N'Digital Engineering', 0, 20, 1);   -- CooldownDays = 0 so you can re-test immediately
GO

/* Point the test rows at real test accounts, e.g.:
UPDATE pulse.Employees SET Upn = N'firstname.lastname@ascendion.com' WHERE EmployeeId = N'E1001';
*/
