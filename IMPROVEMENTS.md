# Webable — Product Review & Improvement Plan

**Target user:** someone who already tracks their money and understands budgets, savings rate, emergency funds and compound growth, but who isn't a power user running a double-entry ledger (hledger, GnuCash) or managing a full portfolio. They want **accurate numbers, low friction, and planning tools that answer "am I on track?"**

This review is based on the current codebase (`app/main.py`, `app/services/*`, `app/templates/*`, `update.md`, `todo.txt`) as of 2026-10-13.

---

## TL;DR — Top 10, in priority order

| # | Change | Why it matters for this audience | Effort |
|---|--------|----------------------------------|--------|
| 1 | **Fix recurrence math** (weekly/yearly/daily entries are counted as monthly) | Wrong numbers lose this audience immediately | S |
| 2 | **Include recurring expenses in category budgets** | "Budget vs spend" currently ignores rent, subscriptions, etc. | S |
| 3 | **CSV / OFX bank import with categorisation rules** | Manual entry is the #1 reason intermediate users quit | L |
| 4 | **Accounts & net worth** (balances, assets, debts) | "Savings total" is just a sum of deposits; no real balance | M–L |
| 5 | **Planned vs actual** per month | The app plans well but never closes the loop with reality | M |
| 6 | **Goals / sinking funds** (target + date → monthly amount) | Core intermediate-level habit; wishlist is a weaker version | M |
| 7 | **Savings rate & a few headline KPIs** on the dashboard | The metrics this audience actually tracks | S |
| 8 | **Rename internal jargon** ("Database calculation", "Mother insights", "IEFP / absence") | The UI currently exposes implementation details | S |
| 9 | **Easier install** than Docker + git + terminal | Your audience isn't necessarily technical | M |
| 10 | **Debt payoff planner** (avalanche / snowball) | The most-requested planner after investment/savings | M |

---

## 1. Correctness issues (fix first)

People who care about their finances will check your math against their bank. These are worth fixing before any new feature.

### 1.1 Recurrence is ignored in the core monthly summary
`instance_service.month_summary()` (`app/services/instance_service.py:768`) adds every active recurring income/expense at **face value** each month:

```python
extras = sum(i["amount"] for i in items["incomes"] if recurring_active_in_month(i, month))
gastos = sum(i["amount"] for i in items["expenses"] if recurring_active_in_month(i, month))
```

So a **€1,200 yearly** insurance shows up as €1,200 *every month*, and a **€50 weekly** grocery run counts as €50/month instead of ~€217. The same happens in `category_breakdown_service.py` (`amount * len(active)`).

Meanwhile `savings_expenses_service.recurrence_to_monthly()` *does* convert correctly — so different pages disagree with each other.

**Fix:** pick one model and use it everywhere:
- *Cash-flow model* (better for this audience): yearly items hit only in their due month, weekly items count the actual number of occurrences in that month. `next_due` already exists in the schema but is unused — this is what it's for.
- Optionally show a "smoothed monthly cost" next to it (yearly ÷ 12) so users can see both.

Add tests for weekly/yearly entries in `tests/test_month_summary_oneoffs.py`.

### 1.2 Category budgets only count one-off transactions
`_category_spend_month()` (`app/main.py:944`) only loops over `oneoffs`. If a user budgets €900 for *Housing* and their rent is a recurring expense, the budget shows €0 spent. Include recurring expenses active that month (with the recurrence fix above).

### 1.3 Currency leaks
Workspaces now have a base currency, but several fields are still named and treated as EUR: `CategoryBudget.monthly_limit_eur`, `WishlistItem.price_eur`, and `emergency_fund_service` ("EUR base"). Wishlist and notes are also **per user**, not per workspace, so a user with a EUR and a BRL workspace has a wishlist with no clear currency. Either attach them to a workspace or store an explicit currency per item.

### 1.4 Savings are deposits, not a balance
`savings_total` is the sum of `savings_deposits`. There's no way to withdraw from savings, record interest, or say "my savings account actually has €8,430". Over time this number drifts from reality, which this audience will notice. See §3.1.

---

## 2. Reduce data-entry friction

Intermediate users already have the discipline to track — what they lack is time. Right now every transaction is typed by hand.

### 2.1 CSV / OFX / CAMT import (highest-impact feature)
You already accept bank statement PDFs, but they're only stored (plus an 8k-char text excerpt); nothing turns into transactions. Almost every bank exports CSV.
- Import wizard: upload → map columns (date, description, amount, debit/credit) → preview → confirm.
- Save the column mapping per bank so the second import is one click.
- **Duplicate detection** on (date, amount, normalised description) — you already hash PDFs, extend the idea.
- Optional later: PDF parsing for the big Portuguese banks (CGD, Millennium, Santander, Novo Banco, ActivoBank) since that's likely your first market.

### 2.2 Auto-categorisation rules
"Description contains `CONTINENTE` → Food". Applied on import and on manual entry. Let users create a rule straight from a transaction ("always categorise like this"). This plus CSV import replaces 90% of manual typing.

### 2.3 Custom categories and sub-categories
`ONEOFF_CATEGORIES` is a fixed list of 11. Intermediate users always want their own (e.g. *Kids*, *Pets*, *Gifts*, *Car → Fuel / Maintenance*). Keep the defaults, allow add/rename/merge, and keep the mapping to the emergency-fund buckets.

### 2.4 Tags and split transactions
- Tags for cross-cutting things: `#holiday-2026`, `#wedding`, `#work-reimbursable`.
- Split one supermarket receipt into Food + Household.

### 2.5 Recurring entries that actually post
Today recurring items are "virtual" — they're computed into each month. Give users the option to have them **materialise as real transactions** on their due date (with a "confirm / adjust amount" step for variable bills like electricity). This is what makes planned vs actual possible (§3.2).

### 2.6 Remove the "Calculate month" step
Users have to click *Calculate month* / *Calculate range* to see results (stored as `JobRun`). Numbers should just be up to date whenever data changes — the calculation is cheap SQLite work.

---

## 3. Features this audience expects

### 3.1 Accounts & net worth
Add an `accounts` table per workspace: checking, savings, credit card, investment, cash, loan/mortgage — each with a starting balance and currency. Transactions belong to an account; transfers between accounts are not income/expense.

This unlocks:
- **Net worth over time** (assets − liabilities), the single most-watched number for this audience.
- Real savings balance instead of the deposit sum (§1.4).
- Manual "update balance" for investment accounts (no need for broker integration).

### 3.2 Planned vs actual
You already have both halves: recurring entries (the plan) and one-offs (reality). Show them side by side per month and per category:

```
Category     Planned   Actual   Diff
Food           400      463     -63  ▲
Transport      120       88     +32
```

The end-of-month summary (`eom_summary`) is the natural place for this.

### 3.3 Goals and sinking funds
Wishlist has name/price/priority/deadline but no progress. Turn it into **goals**:
- Target amount + target date → required monthly contribution, auto-calculated.
- Link to an account or "envelope" and show a progress bar.
- Sinking funds for known irregular costs (car insurance, holidays, Christmas). These pair directly with the yearly-recurrence fix.

### 3.4 Budgets that behave like budgets
Current budgets are one flat monthly limit per category. Add:
- **Rollover** (unspent carries over, overspend reduces next month) — optional per category.
- **Budget templates** — copy last month / auto-suggest from the 3-month average.
- A **zero-based mode** (income − all budgets = 0). Your Learn page already teaches zero-based, envelope and pay-yourself-first; the app should support those methods directly, not just explain them.

### 3.5 Headline KPIs
Put these at the top of the dashboard, each with a trend vs. last month and the 6/12-month average:
- **Savings rate** (% of income saved) — the key number for this audience
- Net worth
- Emergency fund coverage in months (you already compute targets in `emergency_fund_service`)
- Fixed costs as % of income (already computed in `dashboard_metrics.fixed_expenses_summary`)
- Spend this month vs. average, with a "days left / safe to spend per day" figure

### 3.6 Debt payoff planner
Add it next to the investment and savings calculators: list debts with balance, rate and minimum payment → compare **avalanche vs snowball**, payoff date, total interest, and the effect of an extra €X/month. The `debt` bucket already exists in the emergency fund breakdown.

### 3.7 Year-end / annual review
A yearly report: income, spending by category, savings rate, net worth change, biggest changes vs last year. Also helpful for taxes (IRS in Portugal) — tag deductible expenses (health, education, housing) and export them.

### 3.8 Investment tracking (keep it light)
Market Watch shows BTC/SPY quotes, but they're not connected to the user's money. For this audience a light version is enough: holdings (ticker, quantity, cost basis) → current value, allocation pie, contributions vs. growth. Avoid becoming a portfolio tracker; feed the value into net worth.

---

## 4. UX and wording

### 4.1 Remove internal jargon
The UI shows implementation names that mean nothing to users:

| Current | Suggested |
|---|---|
| "Database calculation" | "Monthly overview" |
| "Mother insights output" | "Insights" |
| "Add absence (legacy)" / IEFP mode | Hide unless `enable_iefp_mode` is on, or remove |
| "Calculate month" | (remove; auto-update) |
| "Instance" in URLs/code | Fine internally, but always "workspace" in UI |

### 4.2 One clear home screen
Right now there are two "homes": `/dashboard` (cross-workspace) and `/instances/{id}` (the real work). Make the workspace view the landing page with the KPIs (§3.5), and move cross-workspace comparison to a secondary tab. The `instance.html` page (986 lines) mixes data entry, results, projections, entry lists and AI chat — split into **Overview / Transactions / Budgets / Plan**.

### 4.3 Transactions page
A single transaction list with filters (date range, category, account, tag, amount, text), sorting, bulk edit (re-categorise 20 at once) and inline edit. Search currently only covers one-off transactions.

### 4.4 Onboarding for non-beginners
Skip the tutorial tone; instead offer a **5-minute setup**:
1. Currency & accounts with current balances
2. Income (salary, day of month)
3. Fixed bills (rent, utilities, subscriptions) — with common presets
4. Import last 3 months of CSV → auto-suggested budgets

The user ends with a meaningful dashboard on day one instead of empty charts.

### 4.5 Smarter notifications
The notification bell currently only covers workspace invites. Use it for money:
- Budget at 80% / exceeded
- Upcoming bill in 3 days (from `next_due`)
- Unusually large transaction vs. category average
- Month closed → EOM summary ready
- Goal reached

### 4.6 Mobile and quick capture
Intermediate users log spending on the go. Make sure the quick-add FAB (`quick_add_fab.html`) works well on a phone, remembers the last category, and consider a PWA manifest so it can be installed on the home screen.

---

## 5. Install, trust & data safety

### 5.1 Installation is the biggest funnel leak
The README requires git, Docker, a terminal, and optionally `usermod`. Your audience cares about money, not necessarily about Docker. Options, from easiest to hardest:
- **Desktop builds** — you already have PyInstaller/Windows work in `Windows_Testing/`; ship signed installers for Windows/macOS that start the server and open the browser.
- One-line install scripts per OS.
- Optional hosted/sync version later, kept clearly separate from the local-first promise.

### 5.2 Lean into "local-first" as a selling point
Privacy is a real differentiator against apps that sell aggregated data. Say it clearly on the home page, and back it up:
- **Automatic scheduled backups** (you already have `backup_data_directory`) with a visible "last backup" date and one-click restore.
- Optional **encrypted** export.
- Make clear that market data and currency rates are the only outbound requests, and allow turning them off.

### 5.3 Account security
Even locally, multi-user workspaces need: password change/reset flow, session timeout, optional TOTP 2FA, and a minimum password length.

### 5.4 Audit history in the UI
`FinanceAuditLog` already records changes. Show it in shared workspaces ("Ana changed Rent from €850 to €900, 12 Oct") — important for couples sharing a budget, and an "undo" for accidental deletes.

---

## 6. Shared workspaces (couples / households)

You've built members and invites — households are a strong niche for this audience. Next steps:
- **Who paid** on each transaction and a "who owes whom" balance (Splitwise-lite).
- Personal vs. shared categories in one workspace.
- Viewer vs. editor roles are in the backend; expose them clearly in the invite UI.

---

## 7. AI assistant — make it useful, not decorative

The AI chat is optional and local, which is good. Make it earn its place by focusing on specific questions over the user's own data:
- "Why was I over budget this month?"
- "Which subscriptions did I pay for the last 6 months?"
- "Draft next month's budget from my last 3 months."
- Auto-categorisation suggestions for imported transactions (pairs with §2.2).

Always show the numbers the answer is based on, so users can verify it.

---

## 8. Suggested roadmap

**Phase 1 — Trust the numbers (1–2 weeks)**
Recurrence fix, budgets include recurring, currency cleanup, remove "Calculate month", rename jargon, savings-rate KPI.

**Phase 2 — Stop typing (3–5 weeks)**
CSV import with saved mappings, duplicate detection, categorisation rules, custom categories, unified transactions page with bulk edit.

**Phase 3 — Plan with confidence (4–6 weeks)**
Accounts & net worth, planned vs actual, goals/sinking funds, rollover budgets, budget notifications.

**Phase 4 — Grow**
Desktop installers, debt planner, annual review/tax export, light investment holdings, household "who paid" features, PWA.

---

## What to avoid

- **Going too advanced:** double-entry accounting, lot-level capital gains, options tracking. That's a different audience.
- **Going too beginner:** gamification, streaks, cartoon mascots, long tutorials. This audience finds it patronising.
- **Adding more calculators before fixing the core data.** The investment/savings/emergency calculators are good, but they're only as useful as the numbers fed into them.
