# Pitch Video Script — AI Revenue Recovery Agent

Razorpay Buildathon 2026, Track 3. **2 minutes 35 seconds.** Two shots:
a terminal and a browser.

**The thesis, said once at the top and once at the bottom:**
*we don't just flag revenue at risk — we recover a measured amount of it, and
every rupee traces back to a rule you can read.*

---

## Before you record

```powershell
# 1. Supabase must be awake. Free projects pause after ~a week idle.
python setup_database.py --check      # all four [ok] lines, or restore it first

# 2. Back to round zero, then one clean round.
python reset_demo.py --yes
python run_pipeline.py                # ~45s — let it FINISH before recording

# 3. Dashboard in a second window.
python -m streamlit run dashboard.py
```

Then:

- **Terminal** — scrolled back to the top of the pipeline output. Font size up.
- **Browser** — dashboard loaded, zoomed so the masthead and the money figure
  are both visible without scrolling. Hide bookmarks bar.
- Confirm the badge top-right reads **Dry run**.

**Record the pipeline output, don't run it live.** 45 seconds of scrolling logs
is 30% of your video.

### Numbers after a clean reset — memorise these

| | |
|---|---|
| Payments in batch | **40** |
| At risk | **₹67,382** |
| Tier split | **6** auto-retry · **31** WhatsApp · **3** voice |
| Recovered, no human contact | **₹4,941** |
| Recovery rate | **5.0%** count · **7.3%** by value |
| Outreach cost | **₹24.35** → **203×** return |

Promise-to-pay dates are generated 2–7 days from *today*, so read them off
screen rather than memorising.

---

## The script

### [0:00 – 0:15] · Terminal, top of output

> "Forty failed payments. **₹67,382** at risk.
>
> Today a merchant either writes that off, or pays a call centre to chase all
> forty exactly the same way. Both are wrong — a phone call costs more than a
> ₹200 subscription is worth."

**On screen:** the `Total at risk: Rs 67,382.26` line.

---

### [0:15 – 0:40] · Terminal, scroll Stage 1 slowly

> "Our agent reads each failure and picks the cheapest action that will
> actually work. Every line here carries its reason.
>
> *Retryable failure, first attempt — silent retry, no contact.*
> *B2B invoice, high value — needs a human touch.*
>
> That's not a confidence score. It's a rule. Seven of them, checked in order,
> first match wins. When a compliance officer asks *why did you call me*, there
> is exactly one line to point at."

**On screen:** the reason column on the right. Let two or three lines land.

---

### [0:40 – 1:00] · Terminal, Stage 2

> "Tier one is a silent gateway retry. No message, no call, costs nothing.
> Two of six cleared on re-presentment.
>
> That's **₹4,941 recovered before we contacted a single customer.**"

**On screen:** the two `CAPTURED` lines.

---

### [1:00 – 1:20] · Terminal, Stage 4

> "Only three payments were worth a phone call. Those got a Hinglish voice
> agent running a promise-to-pay script.
>
> What comes back isn't a transcript — it's structured JSON. Did they commit,
> what date, what's the reason for delay. That date goes straight into the
> database as a follow-up."

**On screen:** the three `promise to pay captured for <date>` lines.
Read one reason aloud — *awaiting invoice approval* — it lands well.

---

### [1:20 – 1:50] · Switch to the browser · **the key moment**

Start at the top of the page.

> "One screen. The rule on the left, the money on the right, deliberately at
> the same weight — the number is the consequence, the rule is the decision.
>
> ₹4,941 recovered. Five percent of the batch. Cost of outreach: **₹24**."

**Scroll to "Simulate a customer paying".** Pick the top row —
`65c9e2e1 · ₹4,650 · Priya Gupta`. **Click "Mark as paid".**

> "Customer pays the link. In production that's a Razorpay `payment.captured`
> webhook — same function."

**Scroll back up.** The figure now reads **₹9,591**, rate **7.5%**, by value
**14.2%**.

> "The number moves live. And the audit trail just credited the **WhatsApp**
> tier — so we know which channel earned the money, not just that it arrived."

---

### [1:50 – 2:20] · Keep scrolling

**"How it decides"** — pause on the seven-rule table.

> "The whole engine. No model, no black box."

**"The rules that stop it"** — pause here, this is the compliance beat.

> "Three contact attempts, maximum — and silent retries don't count, because
> they never reach the customer. Calls only between nine and nine.
> Fraud-flagged payments get no automated contact at all.
>
> And the one that matters most: we re-check whether the customer already paid
> **immediately before firing**, not just when we decided. Those are different
> moments."

**"Audit trail"** — in the **Show** filter, tick **Blocked by a rule**.

> "Append-only. Every decision, every send, and every time a rule *refused* to
> send. Refusing to act is as auditable as acting."

---

### [2:20 – 2:35] · Close

> "Detection is the easy half. This is a decision engine with logged outcomes:
> **₹9,591 recovered on a ₹67,382 batch, for ₹24 of outreach**, every action
> traceable to one line of rule.
>
> Run it four times and the three-attempt cap shuts it down on its own."

---

## Two things to say if you have 15 spare seconds

**On dry run** — say it before a judge asks:

> "Sends are simulated, deliberately. Twilio gates WhatsApp templates behind a
> paid upgrade, so rather than let a KYC queue decide whether our demo works,
> every channel sits behind one flag. The live code is complete — flip
> `DRY_RUN=false` and it sends for real. Every simulated row is stamped
> `simulated: true`."

**On verifiability** — strong closer if the repo is on screen:

> "Clone it and run `python test_agent.py`. Fifty-six tests, no credentials
> needed. You can verify the rules without asking us for anything."

---

## If something breaks mid-take

| Problem | Do |
|---|---|
| `getaddrinfo failed` | Supabase project is paused. Restore it in the dashboard. |
| Dashboard stale | **Refresh now** at the bottom. Caches for 15s. |
| Voice tier shows 0 calls | You're outside 9am–9pm. **Say it out loud** — the stopping rule working is a better demo than the call. |
| Numbers don't match | Someone ran a second round. `reset_demo.py --yes` then `run_pipeline.py`. |
| No database at all | `python decision_engine.py` runs the full rules engine off the CSVs, no Supabase. Narrate that instead. |

---

## Don't say

| Don't | Do |
|---|---|
| "It's just a demo" | "Every channel sits behind one flag, by design." |
| "We didn't have time to…" | "That's the next thing we'd build." |
| "The AI decides…" | "The rules decide. That's the point." |
