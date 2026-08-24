"""
dashboard.py — the whole pitch on one screen.

    python -m streamlit run dashboard.py

Reads straight from Supabase. One continuous page, read top to bottom, in
the order the story is told:

    the hero         the governing rule and the money, at equal weight
    what it did      the three tiers, cost-ordered
    promises         what the voice tier captured
    mark as paid     the one control that moves the number
    how it decides   the rules, and the rules that stop it
    audit trail      the proof

No tabs — nothing is hidden behind a click a judge might not make.

Design system is DESIGN.md; the theme that implements it lives in
.streamlit/config.toml. No CSS injection: everything here is a native
Streamlit element, so the page stays consistent if the theme changes.

Two house rules that are easy to break by accident:

    green is recovered money and nothing else, so it is never a button,
    a badge, or a chart series;

    no inline backticks in caption or body text. codeFontSize is 19px so a
    stray backtick renders larger than the sentence around it. Identifiers
    in prose are bold; st.code is reserved for rule statements.
"""

import pandas as pd
import streamlit as st

import config
import db
import decision_engine
import outcome_tracker

st.set_page_config(
    page_title="Revenue recovery agent",
    page_icon=":material/savings:",
    layout="centered",
)

# --- Page chrome -------------------------------------------------------------
#
# The ONE deliberate exception to the no-CSS-injection rule, and it is here
# because Streamlit has no native way to texture a background or to set a
# masthead independently of the heading scale.
#
# The texture is a 22px dot grid in ink at 4.5% — engineering-paper tooth, not
# decoration. It is sized by measurement, not taste: the darkest pixel it can
# produce is #F0EEE9, and every semantic colour still clears its bar against
# THAT rather than against the flat page token (border 3.17:1, muted 5.17:1,
# green 6.15:1). test_agent.py asserts this, so the texture cannot be darkened
# later without the suite failing.
#
# Nothing here changes layout, spacing or type scale — those stay in
# config.toml where they belong.
PAGE_CHROME = """
<style>
  .stApp, [data-testid="stAppViewContainer"] {
      background-color: #FAF8F3;
      background-image: radial-gradient(circle at 1px 1px,
                        rgba(20, 24, 31, 0.045) 1px, transparent 0);
      background-size: 22px 22px;
      background-attachment: fixed;
  }
  [data-testid="stHeader"] { background: transparent; }

  /* Masthead. Fraunces at 40/700 sits above the h1 money figure (44px) as a
     publication name sits above a headline — related, clearly subordinate. */
  .rr-masthead {
      font-family: 'Fraunces', Georgia, serif;
      font-size: 40px;
      font-weight: 700;
      letter-spacing: -0.021em;
      line-height: 1.08;
      color: #14181F;
      margin: 0 0 0.15rem 0;
  }
  .rr-rule {
      height: 2px;
      width: 56px;
      background: #14181F;
      margin: 0.55rem 0 0.15rem 0;
  }
  @media (max-width: 640px) { .rr-masthead { font-size: 30px; } }
</style>
"""
st.markdown(PAGE_CHROME, unsafe_allow_html=True)


TIER_LABELS = {
    "auto_retry": "Auto-retry",
    "whatsapp": "WhatsApp",
    "voice_call": "Voice call",
}
TIER_ORDER = ["auto_retry", "whatsapp", "voice_call"]

TIER_BLURB = {
    "auto_retry": "Silent gateway retry. No customer contact at all.",
    "whatsapp": "Templated nudge with a payment link.",
    "voice_call": "Hinglish call that captures a promise to pay.",
}

# Indicative per-message cost in INR. Assumptions, not billed rates — used
# only to show that the tiers really are cost-ordered.
TIER_UNIT_COST = {"auto_retry": 0.0, "whatsapp": 0.35, "voice_call": 4.50}

OUTCOME_LABELS = {
    "success": "Executed",
    "failed": "Failed",
    "pending": "Waiting",
    "skipped": "Blocked by rule",
}

# Coarse groupings for the audit filter. Ten raw event_type strings are more
# than anyone wants to read; these are the four questions people actually ask.
EVENT_GROUPS = {
    "Decisions": {"decision_made"},
    "Outreach": {"whatsapp_dry_run", "whatsapp_sent", "whatsapp_failed",
                 "voice_dry_run", "voice_call_completed", "voice_call_failed",
                 "auto_retry_dry_run", "auto_retry_attempted"},
    "Recoveries": {"payment_recovered", "recovery_reverted"},
    "Blocked by a rule": {"intervention_skipped"},
}


# --- Data --------------------------------------------------------------------

@st.cache_data(ttl=15, show_spinner="Loading batch from Supabase...")
def load_all():
    """One round trip per table. Everything downstream is cheap filtering on
    top of this, so interacting with the page doesn't re-query."""
    sb = db.get_supabase()
    return {
        "metrics": db.recovery_metrics(sb=sb),
        "transactions": sb.table("transactions").select("*, customers(name, segment)")
                          .order("amount", desc=True).execute().data,
        "interventions": sb.table("interventions").select("*")
                           .order("fired_at", desc=True).execute().data,
        "audit": sb.table("audit_log").select("*")
                   .order("created_at", desc=True).limit(1000).execute().data,
    }


def rupees(amount, decimals=0):
    return f"₹{amount:,.{decimals}f}"


def latest_intervention_by_txn(interventions):
    out = {}
    for iv in sorted(interventions, key=lambda i: i.get("fired_at") or ""):
        out[iv["transaction_id"]] = iv
    return out


# --- Audit-log flattening ----------------------------------------------------

def event_detail(event_type, payload):
    """One readable sentence per audit event. Payload shape differs by event
    type; this is where that gets normalised for display."""
    p = payload or {}

    if event_type == "decision_made":
        return p.get("reason", "")
    if event_type == "intervention_skipped":
        return p.get("reason", "")
    if event_type in ("whatsapp_dry_run", "whatsapp_sent"):
        body = (p.get("body") or "").replace("\n", " ")
        verb = "Would send" if event_type.endswith("dry_run") else "Sent"
        return f"{verb} to {p.get('to', '?')} — {body[:100]}"
    if event_type == "whatsapp_failed":
        return f"Send failed: {p.get('error', '')}"
    if event_type in ("voice_dry_run", "voice_call_completed"):
        r = p.get("structured_result") or {}
        if r.get("promise_to_pay_date"):
            detail = f"promise to pay {r['promise_to_pay_date']}"
        elif not r.get("call_connected"):
            detail = "no answer"
        else:
            detail = "connected, no commitment"
        if r.get("reason_for_delay"):
            detail += f" ({r['reason_for_delay']})"
        return f"{p.get('provider', 'voice')} — {detail}"
    if event_type == "voice_call_failed":
        return f"Call failed: {p.get('error', '')}"
    if event_type in ("auto_retry_dry_run", "auto_retry_attempted"):
        if p.get("captured"):
            return f"Silent retry captured {rupees(float(p.get('amount', 0)), 2)}"
        return p.get("decline_reason", "Retry declined")
    if event_type == "payment_recovered":
        return (f"{rupees(float(p.get('amount', 0)), 2)} received — credited to "
                f"{TIER_LABELS.get(p.get('attributed_tier'), 'no tier')} "
                f"(via {p.get('source', 'manual')})")
    if event_type == "recovery_reverted":
        return "Recovery reverted (demo reset)"
    return ""


def event_tier(event_type, payload):
    p = payload or {}
    for key in ("tier", "attributed_tier"):
        if p.get(key):
            return p[key]
    for prefix, tier in (("whatsapp", "whatsapp"), ("voice", "voice_call"),
                         ("auto_retry", "auto_retry")):
        if event_type.startswith(prefix):
            return tier
    return ""


def build_audit_frame(audit_rows, interventions):
    """Payment, tier, reason, outcome, timestamp — the audit view the brief
    asks for. Outcome is joined from the intervention on the same payment
    and tier."""
    outcomes = {(iv["transaction_id"], iv["tier"]): iv["outcome"]
                for iv in sorted(interventions, key=lambda i: i.get("fired_at") or "")}

    rows = []
    for a in audit_rows:
        payload = a.get("payload") or {}
        tier = event_tier(a["event_type"], payload)
        txn_id = a.get("transaction_id") or ""
        rows.append({
            "When": pd.to_datetime(a["created_at"]),
            "Payment": txn_id[:8],
            "Event": a["event_type"].replace("_", " "),
            "Tier": TIER_LABELS.get(tier, "—"),
            "What happened": event_detail(a["event_type"], payload),
            "Outcome": OUTCOME_LABELS.get(outcomes.get((txn_id, tier)), "—"),
            "_event_type": a["event_type"],
        })

    df = pd.DataFrame(rows)
    return df.sort_values("When", ascending=False) if not df.empty else df


# =============================================================================
#  PAGE
# =============================================================================

data = load_all()
metrics = data["metrics"]
interventions = data["interventions"]
transactions = data["transactions"]

recovered = metrics["total_recovered"]
at_risk = metrics["total_at_risk"]
value_rate = (recovered / at_risk * 100) if at_risk else 0.0
outreach_cost = sum(
    len([i for i in interventions if i["tier"] == t]) * TIER_UNIT_COST[t]
    for t in TIER_ORDER
)

# --- Masthead ----------------------------------------------------------------

left, right = st.columns([3, 1], vertical_alignment="center")
with left:
    st.markdown('<div class="rr-masthead">AI Revenue Recovery</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="rr-rule"></div>', unsafe_allow_html=True)
    st.caption("Razorpay Buildathon 2026  ·  Track 3")
with right:
    if config.DRY_RUN:
        # Not green. Green means recovered money on this page and nothing else,
        # so a status badge may never borrow it. See DESIGN.md.
        st.badge("Dry run", icon=":material/shield:", color="gray")
    else:
        st.badge("Live sending", icon=":material/warning:", color="red")

# --- The hero: the rule and the money, at equal weight ------------------------
#
# The number is the consequence; the rule is the decision. Neither outranks the
# other here. The rule is rendered with st.code so it picks up codeFontSize
# (19px, larger than body) and arrives with a copy button, which means a judge
# can lift the reasoning straight off the screen.

# Count distinct payments per rule, not raw events: the audit log is
# append-only across recovery rounds, so the same payment is decided again on
# every re-run and counting events would report more decisions than payments.
reason_txns = {}
for a_row in data["audit"]:
    if a_row["event_type"] == "decision_made":
        payload = a_row.get("payload") or {}
        reason, txn = payload.get("reason", ""), a_row.get("transaction_id")
        if reason and txn:
            reason_txns.setdefault((reason, payload.get("tier", "")), set()).add(txn)

decided = set().union(*reason_txns.values()) if reason_txns else set()

hero_left, hero_right = st.columns([1.15, 1], vertical_alignment="bottom")

with hero_left:
    if reason_txns:
        (top_reason, top_tier), top_txns = max(reason_txns.items(),
                                               key=lambda kv: len(kv[1]))
        st.code(top_reason, language=None, wrap_lines=True)
        st.caption(
            f"{TIER_LABELS.get(top_tier, top_tier or 'No tier')} — the rule "
            f"behind **{len(top_txns)}** of {len(decided)} payments decided so "
            f"far. Every one of them traces back to a line you can read."
        )
    else:
        st.code("no decisions yet — run the pipeline", language=None,
                wrap_lines=True)
        st.caption("Every decision this agent makes lands here, in the words "
                   "the rule was written in.")

with hero_right:
    st.markdown(f"# {rupees(recovered)}")
    st.markdown(
        f"**recovered** of {rupees(at_risk)} at risk, across "
        f"{metrics['total_transactions']} failed payments."
    )
    st.progress(min(recovered / at_risk, 1.0) if at_risk else 0.0)

a, b, c, d = st.columns(4)
a.metric("Recovery rate", f"{metrics['recovery_rate_pct']:.1f}%",
         help="From the recovery_metrics view: recovered payments divided by "
              "total payments.")
b.metric("By value", f"{value_rate:.1f}%",
         help="Rupees recovered divided by rupees at risk. Differs from the "
              "count-based rate whenever recovered payments are bigger or "
              "smaller than average.")
c.metric("Interventions fired", f"{len(interventions)}")
d.metric("Outreach cost", rupees(outreach_cost, 2),
         delta=f"{recovered / outreach_cost:,.0f}x return" if outreach_cost and recovered else None,
         help="Indicative, not billed: ₹0 per silent retry, ₹0.35 per WhatsApp "
              "message, ₹4.50 per voice call.")

if config.DRY_RUN:
    st.caption(
        ":material/shield: **Dry run.** No message or call leaves the building. "
        "Each one is composed in full and written to the audit trail instead. "
        "The live provider code runs unchanged at **DRY_RUN=false**, and every "
        "simulated row is stamped **simulated: true**."
    )
else:
    st.warning("**Live mode.** Real WhatsApp messages and real phone calls are going out.",
               icon=":material/warning:")

st.divider()

# --- What the agent did ------------------------------------------------------

st.header("What the agent did")
st.caption("Three tiers, cost-ordered. The agent only escalates when a rule "
           "says the cheaper tier will not do.")

iv_df = pd.DataFrame(interventions)
if iv_df.empty:
    st.info("No interventions yet. Run **python run_pipeline.py**, then refresh.",
            icon=":material/info:")
else:
    blocked = {}
    for a_row in data["audit"]:
        if a_row["event_type"] == "intervention_skipped":
            t = (a_row.get("payload") or {}).get("tier", "")
            blocked[t] = blocked.get(t, 0) + 1

    rows = []
    for tier in TIER_ORDER:
        sub = iv_df[iv_df["tier"] == tier]
        if sub.empty:
            continue
        outcomes = sub["outcome"].value_counts().to_dict()
        rows.append({
            "Tier": TIER_LABELS[tier],
            "What it is": TIER_BLURB[tier],
            "Fired": len(sub),
            "Share": len(sub) / len(iv_df),
            "Executed": outcomes.get("success", 0),
            "Blocked by a rule": blocked.get(tier, 0) + outcomes.get("skipped", 0),
            "Cost": len(sub) * TIER_UNIT_COST[tier],
        })

    st.dataframe(
        pd.DataFrame(rows), width="stretch", hide_index=True,
        column_config={
            "Tier": st.column_config.TextColumn(width="small"),
            "What it is": st.column_config.TextColumn(width="large"),
            "Fired": st.column_config.NumberColumn(width="small"),
            "Share": st.column_config.ProgressColumn(
                "Share of batch", min_value=0, max_value=1, format="percent",
                width="small"),
            "Cost": st.column_config.NumberColumn(format="₹%.2f", width="small"),
        },
    )

    total_blocked = sum(blocked.values())
    if total_blocked:
        st.caption(f"**{total_blocked}** intervention(s) were decided, then refused "
                   f"at execution time by a stopping rule. Each is an "
                   f"**intervention_skipped** row in the audit trail below.")

# --- Promises to pay ---------------------------------------------------------

promises = [i for i in interventions if i.get("promise_to_pay_date")]
if promises:
    st.subheader("Promises to pay")
    st.caption("What the voice tier captured — structured data, not a transcript. "
               "This is next week's collections queue, written by the agent.")
    st.dataframe(
        pd.DataFrame([{
            "Payment": p["transaction_id"][:8],
            "Promised for": p["promise_to_pay_date"],
            "What they said": (p.get("notes") or "").split("(reason: ")[-1].rstrip(")")
            if "(reason: " in (p.get("notes") or "") else "—",
        } for p in sorted(promises, key=lambda x: x["promise_to_pay_date"])]),
        width="stretch", hide_index=True,
    )

st.divider()

# --- Mark as paid ------------------------------------------------------------

st.header("Simulate a customer paying")
st.caption("Fires the same **mark_recovered()** that a Razorpay "
           "**payment.captured** webhook would call. The figure at the top moves.")

by_txn = latest_intervention_by_txn(interventions)
open_payments = [t for t in transactions
                 if t["status"] == "failed" and t["id"] in by_txn]

if not open_payments:
    st.success("Every payment that had an intervention has been recovered.",
               icon=":material/check_circle:")
else:
    def _label(t):
        tier = by_txn[t["id"]]["tier"]
        who = (t.get("customers") or {}).get("name", "?")
        return (f"{t['id'][:8]}  ·  {rupees(float(t['amount']))}  ·  {who}"
                f"  ·  chased by {TIER_LABELS.get(tier, tier)}")

    pick, act = st.columns([3, 1], vertical_alignment="bottom")
    with pick:
        choice = st.selectbox(
            "Payment to mark as paid",
            open_payments, format_func=_label,
            help="Sorted by amount, largest first — pick a big one so the "
                 "recovery rate visibly moves.",
        )
    with act:
        if st.button("Mark as paid", type="primary", width="stretch",
                     icon=":material/payments:"):
            ok, msg = outcome_tracker.mark_recovered(choice["id"], source="dashboard")
            load_all.clear()
            st.toast(msg, icon=":material/check_circle:" if ok else ":material/error:")
            st.rerun()

recovered_rows = [t for t in transactions if t["status"] == "recovered"]
if recovered_rows:
    with st.expander(f"Recovered so far ({len(recovered_rows)}) — and how to undo"):
        st.dataframe(
            pd.DataFrame([{
                "Payment": t["id"][:8],
                "Customer": (t.get("customers") or {}).get("name", "?"),
                "Amount": float(t["amount"]),
                "Credited to": TIER_LABELS.get(
                    (by_txn.get(t["id"]) or {}).get("tier"), "—"),
            } for t in recovered_rows]),
            width="stretch", hide_index=True,
            column_config={"Amount": st.column_config.NumberColumn(format="₹%.2f")},
        )
        undo = st.selectbox(
            "Put one back to failed (demo reset only)", recovered_rows,
            format_func=lambda t: f"{t['id'][:8]} · {rupees(float(t['amount']))}",
            key="undo_pick",
        )
        if st.button("Revert to failed", icon=":material/undo:"):
            ok, msg = outcome_tracker.undo_recovered(undo["id"])
            load_all.clear()
            st.toast(msg, icon=":material/undo:" if ok else ":material/error:")
            st.rerun()

st.divider()

# --- How it decides ----------------------------------------------------------

st.header("How it decides")
st.caption("A rules table, not a model. Checked in order, first match wins — "
           "so every tier traces back to exactly one line, and that line is "
           "what gets written to the audit trail.")

st.dataframe(
    pd.DataFrame([
        {"#": 1, "If": "the payment is no longer failed",
         "Then": "skip", "Because": "already resolved"},
        {"#": 2, "If": "it is flagged as fraud risk",
         "Then": "manual review", "Because": "no automated contact, ever"},
        {"#": 3, "If": f"we have already made {decision_engine.MAX_CONTACT_ATTEMPTS} contact attempts",
         "Then": "manual review", "Because": "stopping rule: the cap is reached"},
        {"#": 4, "If": "the failure is retryable and this is the first attempt",
         "Then": "auto-retry", "Because": "a silent retry costs nothing and often works"},
        {"#": 5, "If": f"it is a B2B invoice over {rupees(decision_engine.HIGH_VALUE_THRESHOLD)} or has failed twice",
         "Then": "voice call", "Because": "high value or repeat failure needs a human touch"},
        {"#": 6, "If": f"the customer must act and it is over {rupees(decision_engine.HIGH_VALUE_THRESHOLD)}",
         "Then": "voice call", "Because": "worth a call, not just a text"},
        {"#": 7, "If": "anything else",
         "Then": "WhatsApp", "Because": "the low-cost default nudge"},
    ]),
    width="stretch", hide_index=True,
    column_config={
        "#": st.column_config.NumberColumn(width="small"),
        "If": st.column_config.TextColumn(width="medium"),
        "Then": st.column_config.TextColumn(width="small"),
        "Because": st.column_config.TextColumn(width="medium"),
    },
)

st.subheader("The rules that stop it")
st.markdown(
    f"""Checked when the tier is chosen **and again immediately before anything
fires** — those are different moments, and a customer may have paid in between.

- **Never contact someone who has already paid.** The payment's status is
  re-read at execution time, not trusted from the decision.
- **At most {decision_engine.MAX_CONTACT_ATTEMPTS} contact attempts** per payment.
  Silent retries don't count — they never reach the customer.
- **Calls only between {decision_engine.CALL_WINDOW_START:%H:%M} and
  {decision_engine.CALL_WINDOW_END:%H:%M}.** Outside that, the voice tier is
  downgraded to WhatsApp when deciding, and deferred when executing.
- **Fraud-flagged payments get no automated contact at all.**

Every refusal is written to the audit trail with the rule that caused it, so
declining to act is as auditable as acting."""
)

st.divider()

# --- Audit trail -------------------------------------------------------------

st.header("Audit trail")
st.caption("Append-only. Every decision, every send, every rule that refused "
           "to send, every rupee recovered.")

audit_df = build_audit_frame(data["audit"], interventions)

if audit_df.empty:
    st.info("Audit trail is empty. Run **python run_pipeline.py**, then refresh.",
            icon=":material/info:")
else:
    f1, f2 = st.columns([2, 3])
    groups = f1.multiselect("Show", list(EVENT_GROUPS), default=[],
                            placeholder="Everything")
    search = f2.text_input("Search", "",
                           placeholder="Payment id, customer, or reason...")

    view = audit_df
    if groups:
        wanted = set().union(*(EVENT_GROUPS[g] for g in groups))
        view = view[view["_event_type"].isin(wanted)]
    if search:
        s = search.strip().lower()
        view = view[view["Payment"].str.lower().str.contains(s)
                    | view["What happened"].str.lower().str.contains(s)]

    st.caption(f"Showing {len(view)} of {len(audit_df)} events.")
    st.dataframe(
        view.drop(columns=["_event_type"]),
        width="stretch", hide_index=True, height=420,
        column_config={
            "When": st.column_config.DatetimeColumn(format="DD MMM  HH:mm:ss",
                                                    width="small"),
            "Payment": st.column_config.TextColumn(width="small"),
            "Event": st.column_config.TextColumn(width="small"),
            "Tier": st.column_config.TextColumn(width="small"),
            "What happened": st.column_config.TextColumn(width="large"),
            "Outcome": st.column_config.TextColumn(width="small"),
        },
    )

    st.download_button(
        "Export as CSV", view.drop(columns=["_event_type"]).to_csv(index=False).encode("utf-8"),
        file_name="audit_trail.csv", mime="text/csv", icon=":material/download:",
    )

st.divider()
foot_l, foot_r = st.columns([3, 1], vertical_alignment="center")
foot_l.caption("Reads live from Supabase. Data refreshes every 15 seconds.")
with foot_r:
    if st.button("Refresh now", icon=":material/refresh:", width="stretch"):
        load_all.clear()
        st.rerun()
