# Ascendion Pulse – Launcher + Teams Card POC

A dummy but working setup for sending Pulse cards to employees in Teams through Power Automate, and capturing their answers.
It covers **Launcher (block 4)** and **Teams Card (block 5)** only.

| Stage | What you build | Needs | Time |
|---|---|---|---|
| **A. Card test** | 1 flow: you type a UPN, the card arrives in Teams, the answer shows in the run history | Teams + Power Automate (standard licence) | ~15 min |
| **B. Launcher POC** | Azure SQL dummy DB + 1 flow: plan → send to every eligible test user → save answers anonymously | + Azure SQL DB, **Power Automate Premium** (SQL connector is premium) | ~1–2 h |

Do **A first**. It shows the exact shape of the response payload in your tenant, which Stage B relies on.

```
poc/
├─ cards/01_test_card_static.json   Stage A card (fixed text)
├─ cards/02_pulse_card_flow.json    Stage B card (question text from SQL via @{items(...)})
└─ sql/01_schema.sql · 02_seed.sql · 03_procedures.sql · 99_reset_demo.sql
```

---

## Before you start

- The **Workflows** app (Flow bot) must be allowed in your Teams admin app policy. Cards arrive from "Workflows".
- Test users must have Teams. Use your own account and 1–2 teammates who agreed to test.
- **Rename actions exactly as written below *before* writing expressions.** The expressions refer to these names (spaces become `_`).
- You can preview the card at <https://adaptivecards.io/designer> (choose the *Microsoft Teams* host).

---

## Stage A – Card test flow (no database)

**Flow name:** `Pulse POC - Test Card` (Instant cloud flow)

1. **Trigger:** *Manually trigger a flow* → add a text input `RecipientUPN`.
2. **Microsoft Teams → Post adaptive card and wait for a response**. Rename it **`Post Pulse Card`**.
   - Post as: `Flow bot` · Post in: `Chat with Flow bot`
   - Recipient: `RecipientUPN` (dynamic content)
   - Message: paste the whole of `cards/01_test_card_static.json`
   - Update message: `Thanks - your response has been recorded. Results are only shared for groups of 8 or more.`
   - Should update card: `Yes` (replaces the card, so answers don't stay visible in the chat)
   - **⋯ → Settings → Timeout:** `PT1H`
   - Leave **Secure outputs OFF** in Stage A only, so you can inspect the payload. Answer with test data only.
3. **Data Operation → Compose**, rename **`Parsed Response`**, and enter the JSON below. If the designer doesn't convert the `@{...}` parts, add each one through the expression (fx) editor.

```json
{
  "responder":  "@{coalesce(body('Post_Pulse_Card')?['responder']?['userPrincipalName'], body('Post_Pulse_Card')?['responder']?['email'])}",
  "submitId":   "@{body('Post_Pulse_Card')?['submitActionId']}",
  "action":     "@{body('Post_Pulse_Card')?['data']?['action']}",
  "q1":         "@{body('Post_Pulse_Card')?['data']?['q1']}",
  "q2":         "@{coalesce(body('Post_Pulse_Card')?['data']?['q2_good'], body('Post_Pulse_Card')?['data']?['q2_mid'], body('Post_Pulse_Card')?['data']?['q2_bad'])}",
  "followUp":   "@{body('Post_Pulse_Card')?['data']?['fu_bad']}",
  "hrFollowup": "@{coalesce(body('Post_Pulse_Card')?['data']?['hr_good'], body('Post_Pulse_Card')?['data']?['hr_mid'], body('Post_Pulse_Card')?['data']?['hr_bad'])}"
}
```

**Test:** run the flow with your own UPN, open Teams → *Workflows* chat, and answer the card.
Then open the run and check the **raw outputs of `Post Pulse Card`**. Confirm the names `responder.userPrincipalName` (or `email`), `submitActionId` and `data.*`. If your tenant uses different names, fix the expressions here and in Stage B.

---

## Stage B – Launcher POC (Azure SQL)

### B1. Database
1. Create (or reuse) an **empty DEV Azure SQL database**.
2. Edit `sql/02_seed.sql` and replace the `test.userN@yourtenant.com` UPNs with your real test accounts.
3. Run the scripts in order: `01_schema.sql` → `02_seed.sql` → `03_procedures.sql` (Azure portal Query editor, SSMS or Azure Data Studio).
4. Sanity check: `EXEC pulse.usp_PlanLaunch @CampaignCode = N'POC-PULSE-01';` should return 3 launches plus a funnel showing E1004 (no UPN) and E1005 (inactive) excluded. Then run `99_reset_demo.sql` to clear that test launch.

What the procedures do:

| Procedure | Role |
|---|---|
| `usp_PlanLaunch` | Applies eligibility (active, has UPN, nothing pending, cooldown), matches **2 approved questions** (least recently seen), caps the run at `MaxPerRun`, writes `Launch_Tracking`. Returns **Table1** = cards to send and **Table2** = funnel (who was left out and why). |
| `usp_RecordResponse` | Checks that the responder is the person the card was sent to. Writes answers to `Listen_Response` **with no EmployeeId, no LaunchId, date only**. Writes `HR_Followup` (name only) if the employee asked. Marks the launch Completed or Skipped. Safe to retry. |
| `usp_SetLaunchStatus` | Marks a launch Expired (no answer in time) or Failed. |

### B2. Flow
**Flow name:** `Pulse POC - Launcher`. Create it inside a **solution** so it can later move to TEST/PROD.

1. **Trigger:** *Manually trigger a flow*. Later, swap it for *Recurrence* (daily).
2. **SQL Server → Execute stored procedure (V2)**, rename **`Plan Launch`**
   - Procedure: `[pulse].[usp_PlanLaunch]` · CampaignCode: `POC-PULSE-01`
3. **Compose**, rename **`Funnel`**: `body('Plan_Launch')?['ResultSets']?['Table2']`. Its output in the run history shows who was left out and why.
4. **Apply to each**, rename **`For each launch`**
   - Items: `body('Plan_Launch')?['ResultSets']?['Table1']`
   - **Settings → Concurrency control ON, degree 20.** Each iteration waits for its own employee.
   - Inside the loop:

   **4a. Scope `Try`**
   - **Compose**, rename **`Card`**: paste the whole of `cards/02_pulse_card_flow.json`
   - **Post adaptive card and wait for a response**, rename **`Post Pulse Card`**
     - Flow bot · Chat with Flow bot · Recipient: `items('For_each_launch')?['Upn']`
     - Message: `string(outputs('Card'))`
     - Update message and Should update card: same as Stage A
     - Settings: Timeout `PT4H` (use `PT5M` when testing expiry) · **Secure outputs ON**
   - **Execute stored procedure (V2)**, rename **`Record Response`**: `[pulse].[usp_RecordResponse]`. **Settings → Secure inputs ON**

     | Parameter | Expression |
     |---|---|
     | LaunchId | `items('For_each_launch')?['LaunchId']` |
     | ResponderUpn | `coalesce(body('Post_Pulse_Card')?['responder']?['userPrincipalName'], body('Post_Pulse_Card')?['responder']?['email'])` |
     | Action | `coalesce(body('Post_Pulse_Card')?['data']?['action'], 'submit')` |
     | Q1Answer | `body('Post_Pulse_Card')?['data']?['q1']` |
     | Q2Answer | `coalesce(body('Post_Pulse_Card')?['data']?['q2_good'], body('Post_Pulse_Card')?['data']?['q2_mid'], body('Post_Pulse_Card')?['data']?['q2_bad'])` |
     | FollowUpText | `body('Post_Pulse_Card')?['data']?['fu_bad']` |
     | HrFollowup | `coalesce(body('Post_Pulse_Card')?['data']?['hr_good'], body('Post_Pulse_Card')?['data']?['hr_mid'], body('Post_Pulse_Card')?['data']?['hr_bad'], 'false')` |

   **4b. Scope `Catch`.** Use *Configure run after*: run only when `Try` **has failed** or **has timed out**.
   - **Execute stored procedure (V2)**, rename **`Set Status`**: `[pulse].[usp_SetLaunchStatus]`
     - LaunchId: `items('For_each_launch')?['LaunchId']`
     - Status: `if(equals(actions('Post_Pulse_Card')?['status'], 'TimedOut'), 'Expired', 'Failed')`
     - Reason: `coalesce(actions('Post_Pulse_Card')?['error']?['message'], actions('Record_Response')?['error']?['message'], 'unknown')`

```
Trigger → Plan Launch → Funnel → For each launch (×20 parallel)
                                   ├─ Try:   Card → Post Pulse Card (wait) → Record Response
                                   └─ Catch: Set Status (Expired / Failed)
```

---

## Test script

Run `99_reset_demo.sql` between rounds if needed. `CooldownDays = 0` in the seed lets you re-test immediately.

| # | Do this | Expect in Teams | Expect in SQL |
|---|---|---|---|
| 1 | Run the flow | Each test user gets a card; E1004/E1005 get nothing | `Funnel` output lists the excluded people with reasons; `Launch_Tracking` rows `Sent` |
| 2 | Click 😀, rate 4, Submit | Card is replaced by the thank-you text | Launch `Completed`; one `Listen_Response` row with **no employee link**, date only |
| 3 | Click 😟, type text, rate 2, toggle HR, Submit | Thank-you text | `Listen_Response` holds the text; `HR_Followup` holds the **name only** |
| 4 | Click *Skip this time* | Thank-you text | Launch `Skipped`; no response row |
| 5 | Set timeout `PT5M`, don't answer | Card stays; clicking after expiry shows an error | Launch `Expired` (check that the `TimedOut` status name matches in your run) |
| 6 | Run again while a card is still open | No second card for that person | Funnel shows "pulse already pending" |
| 7 | Open the flow run history | – | `Post Pulse Card` and `Record Response` show **secured** content, not answers |
| 8 | Try on Teams **mobile** and **web** | Card renders, buttons and branching work | – |

Useful checks:
```sql
SELECT Status, COUNT(*) FROM pulse.Launch_Tracking GROUP BY Status;
SELECT * FROM pulse.Listen_Response;
SELECT TOP 20 * FROM pulse.Process_Audit ORDER BY EventTime DESC;
```

---

## Known POC limitations (deliberate, not for production)

- **The run stays open until everyone answers or times out.** That's fine for a handful of users. For larger groups, move the loop body into a **child flow** (one per employee) or a separate dispatcher flow.
- **Throttling:** the Flow bot allows about **25 posts per 5 minutes per connection**. `MaxPerRun = 20` keeps one run under that. Larger groups need staggered runs.
- **No reminders yet** (Flow 4), no "remind me later", and no closure summary beyond the update message.
- **Question 1 answers are fixed** (Manageable / Sometimes heavy / Overwhelming), so the follow-up branch works with buttons (`Action.ShowCard`).
- **Cards come from "Workflows", not a branded "Ascendion Pulse" bot.**
- **Connections run as the person who built the flow.** Production needs a dedicated, licensed service account. The Teams connector appears not to support a service principal; confirm this.
- **Card version `1.4`** for wide Teams compatibility. Move to 1.5 only after the mobile check.
- **Use a DEV database with dummy data only.** No reporting or N ≥ 8 suppression is built here.
