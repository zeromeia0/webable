# Latest Update

Welcome to Webable. Release notes for each version are listed here before every push to **main**.

## Current release

- **Edit any entry:** income, expenses, savings deposits and one-time transactions now have an **Edit** button next to Delete. You can change the name, amount, category, date, frequency, start/end dates, fixed/variable type, or move the entry to another workspace. Totals, projections and charts update right away.
- **Members by username:** invite other users by their **username** (no more e-mail links). They get an in-app notification and can **Accept** or **Decline**. All members work on the **same** workspace data. Owners can remove members, cancel pending invites and delete the workspace; members can view and edit data but cannot delete the workspace or remove the owner.
- **Notification bell** in the top bar with an unread badge: invitations received, accepted or declined, and removal from a workspace. Notifications are kept after logout or refresh.
- **Workspaces per currency:** pick a base currency (EUR, USD, GBP, BRL) when you create a workspace. Data, charts, reports and exports stay separate per workspace and are never converted or mixed. Existing workspaces keep EUR.
- **Long-term projections:** charts now show **what you contribute** and **what compounding adds** as separate layers, with a per-month tooltip (total contributed, compound growth, projected balance) and a summary (initial investment, monthly contribution, total contributions, compound growth, final balance). Supports an initial amount, contributions at the start or end of the month, and 0% or negative returns. The rate rule is shown on screen.
- **Dashboard spending breakdown:** expenses by category with amount, share and number of entries. Time ranges: this month, last month, 3 / 6 / 12 months, or all time. Click a category to see its entries. Also shows fixed vs variable spending (you mark expenses as fixed or variable yourself).
- **Clearer download names:** every export is now named `Webable_<Workspace>-<Currency>_<Report>_<Period>.<ext>`, for example `Webable_Personal-EUR_Spending-Report_2026-07-12_to_2026-10-12.pdf`.
- Fixes: read-only (viewer) members can no longer add or delete entries through the server. Dashboard insights no longer add up workspaces that use different currencies.

## Previous release

- Added import / export option
- Added multi-user workspace sharing
- Fixed balance after adding savings amount
