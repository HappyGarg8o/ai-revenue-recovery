# AI Revenue Recovery Agent

**Razorpay Buildathon 2026 — Track 3**

When a payment fails, most businesses do one of two things: write it off, or
pay a call centre to chase every failure identically. Both are wrong. Chasing
a ₹200 subscription with a phone call costs more than the payment is worth;
sending a ₹20,000 B2B invoice a templated SMS wastes the relationship.

This agent reads a batch of failed payments, diagnoses each one, and picks the
**cheapest recovery action that will actually work** — from a seven-rule table
you can read, not a model you have to trust. It refuses to act when a stopping
rule says no, and it writes down every decision, every send, and every refusal.

> **The one-sentence constitution:** *every rupee recovered traces back to a
> rule you can read.*

On the sample batch of 40 failed payments (₹67,382 at risk), a single pass
recovers **₹4,941 for ₹24.35 of outreach** — before a human contacts anyone.

---

## Contents

- [How it works](#how-it-works)
- [The three tiers](#the-three-tiers)
- [The rules](#the-rules)
- [The stopping rules](#the-stopping-rules)
- [Dry run — why nothing actually sends](#dry-run--why-nothing-actually-sends)
- [**Install and run**](#install-and-run)
- [Daily use](#daily-use)
- [Tests](#tests)
- [Project layout](#project-layout)
- [Going live](#going-live)
- [Troubleshooting](#troubleshooting)

---

## How it works

```
   failed payment
         |
         v
   decide_tier()          seven ordered rules -> a tier, plus the
         |                one-sentence reason. Both written to audit_log.
         v
   interventions row      outcome: pending
         |
         v
   stopping_rules.check() re-reads the payment NOW, not at decision time:
         |                already paid? attempts used up? outside call hours?
         v
   channel executor       auto_retry | whatsapp | voice_call
         |                each one gated behind DRY_RUN
         v
   audit_log              what was sent — or which rule refused to send it
         |
         v
   mark_recovered()       payment -> recovered, credited to the tier that
                          earned it
```

The design decision worth calling out: **the stopping rules run twice.** Once
when the tier is chosen, and again immediately before anything fires. Those are
different moments, and a customer may have paid in between. The second check is
what stops you texting someone who already settled up.

---

## The three tiers

Cost-ordered. The agent escalates only when a rule says the cheaper tier will
not do.

| Tier | What it does | Indicative cost | When |
|---|---|---|---|
| **Auto-retry** | Silent gateway re-presentment. No customer contact at all. | ₹0 | Retryable failure (bank timeout, processing error) on its first attempt |
| **WhatsApp** | Templated nudge carrying a payment link. | ~₹0.35 | The default for customer-action failures — expired card, insufficient funds |
| **Voice call** | Hinglish call that captures a verbal promise to pay, returned as structured JSON. | ~₹4.50 | High-value payments, and repeat B2B invoice failures |

Costs are assumptions used to show the ordering, not billed rates.

---

## The rules

Checked in order. **First match wins.** That is the entire explanation — and
the matching line is what gets written to the audit trail.

| # | If | Then | Because |
|---|---|---|---|
| 1 | the payment is no longer failed | `skip` | already resolved |
| 2 | it is flagged as fraud risk | `manual_review` | no automated contact, ever |
| 3 | 3 contact attempts already made | `manual_review` | stopping rule: the cap is reached |
| 4 | retryable failure, first attempt | **`auto_retry`** | a silent retry costs nothing and often works |
| 5 | B2B invoice ≥ ₹5,000, or failed twice | **`voice_call`** | high value or repeat failure needs a human touch |
| 6 | customer must act and it is ≥ ₹5,000 | **`voice_call`** | worth a call, not just a text |
| 7 | anything else | **`whatsapp`** | the low-cost default nudge |

**Why a rules table and not a model.** The deliverable is a *defensible*
decision, not a marginally more accurate one. When a compliance officer — or an
annoyed customer — asks "why did you call me?", there is exactly one line to
point at. A black box cannot do that. With ten million payments behind it, the
thresholds are exactly where you would tune it.

---

## The stopping rules

Enforced when the tier is chosen **and re-checked immediately before anything
fires**.

| Rule | Behaviour |
|---|---|
| **Already paid** | Never contact someone who has settled. Status is re-read at execution time, not trusted from the decision. |
| **Max 3 contact attempts** | Hard cap per payment. Silent auto-retries do **not** count — they never reach the customer. |
| **9am–9pm calling window** | TRAI-aligned. Outside it the voice tier is downgraded to WhatsApp when deciding, and deferred when executing. |
| **Fraud-flagged** | No automated contact at all. |
| **No longer failed** | Anything that left the recovery funnel is dropped. |

Every refusal becomes an `intervention_skipped` row naming the exact rule, so
**declining to act is as auditable as acting.**

Each run of `run_pipeline.py` is one recovery *round*. Run it repeatedly and
the cap shuts the whole thing down on its own:

```
round 1    6 auto-retry, 31 WhatsApp, 3 voice
round 2   30 WhatsApp, 3 voice          (recovered ones drop out)
round 3   30 WhatsApp, 3 voice
round 4    0 customer contact           <- the 3-attempt cap has closed it
```

---

## Dry run — why nothing actually sends

`DRY_RUN` defaults to **true**, and it is a design constraint rather than a
placeholder.

| `DRY_RUN=true` (default) | `DRY_RUN=false` |
|---|---|
| The exact message or call script is composed in full | The real Twilio / Bolna APIs are called |
| Written to `audit_log` as `whatsapp_dry_run`, `voice_dry_run` | Written as `whatsapp_sent`, `voice_call_completed` |
| Intervention marked executed, so recovery maths works | Marked from the real provider response |
| **No third-party credentials needed** | Real, verified credentials required |

This exists because the project hit a real wall: Twilio requires an approved
Content Template for WhatsApp sends outside the 24-hour session window, and
those are gated behind a paid account upgrade. A demo must never depend on
somebody's KYC queue finishing on time.

The live code paths are complete, not stubs — flip the flag and the same
functions send for real. **Every simulated row is stamped `simulated: true`**
in its audit payload, so a dry-run number can never be mistaken for a real one.

---

## Install and run

### What you need

- **Python 3.11 or newer** (`python --version`)
- **A free Supabase account** — [supabase.com](https://supabase.com). This is
  the only external service required.

No Twilio, Bolna or Razorpay account is needed to run this project.

### 1. Clone and install

```bash
git clone https://github.com/<your-username>/ai-revenue-recovery.git
cd ai-revenue-recovery

python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 2. Create a Supabase project

1. Go to [supabase.com/dashboard](https://supabase.com/dashboard) → **New project**.
2. Wait for it to finish provisioning (about a minute).
3. Open **Project Settings → API** and copy two things:
   - the **Project URL** (`https://xxxx.supabase.co`)
   - the **`service_role`** key — *not* the `anon` key

### 3. Add your credentials

```bash
cp .env.example .env
```

Open `.env` and fill in the two values:

```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJhbGci...
```

Leave everything else as it is. `DRY_RUN=true` is what keeps the project from
needing any other account.

> `.env` is gitignored. Never commit it — the `service_role` key bypasses
> row-level security and grants full access to your database.

### 4. Create the tables

This is the one manual step. Supabase's API does not accept schema changes, so
the tables have to be created from the dashboard:

1. Open your project → **SQL Editor** → **New query**
2. Paste the entire contents of [`schema.sql`](schema.sql)
3. Press **Run**

That creates four tables (`customers`, `transactions`, `interventions`,
`audit_log`) and the `recovery_metrics` view.

### 5. Load the sample batch

```bash
python setup_database.py
```

Verifies your credentials, checks all four tables exist, and loads 15 customers
and 40 failed payments. If anything is missing it tells you exactly what to
fix. Use `--check` to verify without changing anything.

### 6. Run it

```bash
python run_pipeline.py
```

Decides a tier for all 40 payments, then executes all three tiers in dry run.
Takes about 45 seconds.

### 7. Open the dashboard

```bash
python -m streamlit run dashboard.py
```

Your browser opens at `http://localhost:8501`.

---

## Daily use

| Command | What it does |
|---|---|
| `python run_pipeline.py` | One full recovery round: decide → auto-retry → WhatsApp → voice |
| `python run_pipeline.py --skip-decide` | Execute pending interventions without starting a new round |
| `python -m streamlit run dashboard.py` | The dashboard |
| `python reset_demo.py --yes` | Clear interventions and audit log, put every payment back to failed |
| `python outcome_tracker.py --list` | Show payments that can be marked recovered |
| `python outcome_tracker.py <payment-id>` | Mark one as paid from the CLI |
| `python setup_database.py --check` | Verify the database without changing it |
| `python test_agent.py` | Run the test suite |

The dashboard has a **Mark as paid** control that fires the same
`mark_recovered()` a real Razorpay `payment.captured` webhook would call, so
you can move the recovery rate live.

---

## Tests

```bash
python test_agent.py          # no pytest needed
pytest test_agent.py -q       # or with pytest, if you have it
```

**56 tests, and none of them need credentials.** That is deliberate: clone this
repo with no `.env` at all and you can still verify every claim this README
makes about the rules and the stopping rules. Nothing in the suite touches
Supabase or any third-party API.

| Area | What is asserted |
|---|---|
| `DRY_RUN` | Defaults to true — if this ever flips, a demo run messages real people |
| Rules | One test per rule, in order, plus precedence (fraud beats high-value) |
| Reasons | No rule may return an empty explanation — the audit trail depends on it |
| Contact accounting | `auto_retry` never burns one of the 3 permitted contacts |
| Call window | Daytime, late night, early morning, and both 9:00 / 21:00 edges |
| Stopping rules | Already-paid, written-off, vanished, at-cap, defer-outside-hours |
| WhatsApp dry run | Sends nothing, fabricates no message id, body carries amount + link + opt-out |
| Voice dry run | Returns structure not a transcript; deterministic; survives junk from a provider |
| Theme | Contrast on text, on control borders, and on the darkest pixel the background texture can produce |

---

## Project layout

```
├── run_pipeline.py             START HERE — all four stages end to end
├── decision_engine.py          the rules table; decide_tier() is the core
├── stopping_rules.py           the execution-time guard every action passes
├── auto_retry_executor.py      tier 1 — silent gateway retry
├── whatsapp_notifier.py        tier 2 — Twilio WhatsApp nudge
├── voice_caller.py             tier 3 — Bolna / Vapi promise-to-pay call
├── outcome_tracker.py          mark_recovered() — closes the loop
├── dashboard.py                the Streamlit dashboard
│
├── config.py                   environment and the DRY_RUN flag
├── db.py                       every Supabase read and write
│
├── setup_database.py           one-time setup and seeding
├── reset_demo.py               wipe interventions + audit log for a fresh run
├── generate_synthetic_data.py  regenerate the sample batch
├── test_agent.py               56 tests, no credentials required
│
├── schema.sql                  tables + the recovery_metrics view
├── data/                       the seed batch as CSV
├── DESIGN.md                   the design system
└── DEMO_SCRIPT.md              three-minute pitch script
```

---

## Going live

Everything below is optional — the project runs fully without any of it.

**WhatsApp.** Set `DRY_RUN=false` and add `TWILIO_ACCOUNT_SID` /
`TWILIO_AUTH_TOKEN`. On a trial account, use the WhatsApp Sandbox: send
`join <your-code>` to the sandbox number from your own phone, which opens a
24-hour window in which free-form messages are delivered without a template.
Point it at your own number — the sample customer numbers are randomly
generated and will fail.

**Voice.** Add `BOLNA_API_KEY` and `BOLNA_AGENT_ID` (or the Vapi equivalents).
The provider is auto-detected from whichever key is present; force it with
`VOICE_PROVIDER=bolna|vapi`. The agent runs a promise-to-pay script and returns
structured JSON, which lands in `interventions.promise_to_pay_date`.

**Payment links.** `PAYMENT_LINK_BASE` defaults to a stub that does not
resolve. Point it at a real Razorpay Payment Link before showing the message to
anyone.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `SUPABASE_URL / SUPABASE_KEY are not set` | You have no `.env`. Run `cp .env.example .env` and fill in both values. |
| `missing tables: ...` | Step 4 was skipped. Paste `schema.sql` into the Supabase SQL editor and run it. |
| `Invalid API key` | You probably copied the `anon` key. Use **`service_role`**. |
| `recovery_metrics view is missing` | Run the last statement in `schema.sql` — the dashboard needs it. |
| Dashboard shows nothing | Run `python run_pipeline.py` first, then hit **Refresh**. |
| Voice tier reports 0 calls | You are outside the 9am–9pm window. That is the stopping rule working correctly. |
| `streamlit: command not found` | Use `python -m streamlit run dashboard.py`. |
| Theme looks wrong after editing | `.streamlit/config.toml` loads only at startup — restart Streamlit. |
| Numbers do not match the demo script | Someone ran a second round. `python reset_demo.py --yes`, then `python run_pipeline.py`. |

---

## Notes and limitations

- **The auto-retry gateway is a stub.** There is no real payment gateway
  integration; re-presentment is simulated deterministically, seeded from the
  payment id so results are reproducible. Simulated captures do mark the
  payment recovered, and are stamped `simulated: true`.
- **`recovery_rate_pct` is count-based** (recovered payments ÷ total payments).
  The dashboard shows the value-weighted rate next to it, because the two
  differ whenever recovered payments are larger or smaller than average.
- **Blocked interventions are stored as `failed`.** The deployed `outcome`
  constraint permits only `pending | success | failed`; the rule that refused
  is recorded in `notes` and in the audit trail.
  [`migration_add_skipped_outcome.sql`](migration_add_skipped_outcome.sql) adds
  a distinct `skipped` value if you want one.
- **Not built, deliberately:** a real Razorpay webhook listener.
  `mark_recovered()` is exactly the function it would call.

---

## License

[MIT](LICENSE).
