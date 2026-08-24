"""
decision_engine.py — Revenue Recovery Agent core decision engine.

Reads failed transactions, decides an intervention tier per transaction
using an explainable rules table, enforces stopping rules before firing
anything, and logs every decision (this is your audit trail).

Requires: pip install supabase   (only if using live Supabase mode)
Env vars: SUPABASE_URL, SUPABASE_KEY (service role key, hackathon-simple)

No env vars set -> dry-runs against data/transactions.csv + data/customers.csv
in the current directory, so you can test the logic before wiring credentials.
"""

import os
import csv
from datetime import datetime, time as dtime

HIGH_VALUE_THRESHOLD = 5000        # INR — above this, escalate faster
MAX_CONTACT_ATTEMPTS = 3           # stopping rule: hard cap on outreach
CALL_WINDOW_START = dtime(9, 0)    # TRAI-aligned calling window
CALL_WINDOW_END = dtime(21, 0)

# Tiers that actually put a message in front of a customer. auto_retry is a
# silent gateway retry, so it does not count against MAX_CONTACT_ATTEMPTS.
# stopping_rules.py imports this so decision time and execution time can
# never disagree about what "a contact attempt" means.
CONTACT_TIERS = ("whatsapp", "voice_call")


def decide_tier(transaction, contact_count):
    """
    Returns (tier, reason). tier is one of:
    'skip', 'manual_review', 'auto_retry', 'whatsapp', 'voice_call'.
    Rules are checked in order — first match wins. Keep this order;
    it's the entire explanation you need to give a judge.
    """
    status = transaction["status"]
    category = transaction["diagnosis_category"]
    amount = float(transaction["amount"])
    attempt_count = int(transaction["attempt_count"])
    segment = transaction.get("segment", "b2c_subscription")

    if status != "failed":
        return "skip", "already resolved"

    if category == "fraud_risk":
        return "manual_review", "fraud-flagged — no automated contact"

    if contact_count >= MAX_CONTACT_ATTEMPTS:
        return "manual_review", f"stopping rule: {MAX_CONTACT_ATTEMPTS} contact attempts reached"

    if category == "retryable" and attempt_count == 0:
        return "auto_retry", "retryable failure, first attempt — silent retry, no contact"

    if segment == "b2b_invoice" and (amount >= HIGH_VALUE_THRESHOLD or attempt_count >= 2):
        return "voice_call", "B2B invoice, high value or repeat failure — needs a human touch"

    if category == "customer_action" and amount >= HIGH_VALUE_THRESHOLD:
        return "voice_call", "high-value customer-action failure — worth a call, not just a text"

    return "whatsapp", "default tier — low-cost nudge with payment link"


def within_call_window(now=None):
    now = now or datetime.now()
    return CALL_WINDOW_START <= now.time() <= CALL_WINDOW_END


# --- Live Supabase run ---
def run_with_supabase(force=False):
    """Decide a tier for every failed transaction and write the decision to
    `interventions` + `audit_log`.

    Re-runnable by design: a transaction that already has an intervention
    waiting to be executed is left alone, so running the pipeline twice does
    not double-contact a customer or inflate the audit trail. Pass
    force=True to decide again anyway.
    """
    import db  # local import so the CSV dry run needs no Supabase deps

    sb = db.get_supabase()

    transactions = (
        sb.table("transactions").select("*, customers(segment)")
        .eq("status", "failed").order("created_at", desc=False).execute().data
    )
    contact_counts = db.contact_counts(sb=sb)

    pending_rows = (
        sb.table("interventions").select("transaction_id")
        .eq("outcome", "pending").execute().data
    )
    already_pending = {row["transaction_id"] for row in pending_rows}

    counts = {}
    skipped = 0

    for t in transactions:
        customer = t.get("customers") or {}
        t["segment"] = customer.get("segment", "b2c_subscription")

        if t["id"] in already_pending and not force:
            skipped += 1
            print(f"{t['id'][:8]}  Rs {float(t['amount']):>10.2f}  "
                  f"{'-- pending --':15}  already decided, awaiting execution")
            continue

        contact_count = contact_counts.get(t["id"], 0)
        tier, reason = decide_tier(t, contact_count)

        if tier == "voice_call" and not within_call_window():
            tier, reason = "whatsapp", "voice tier selected but outside call window — downgraded to WhatsApp"

        db.log_audit(t["id"], "decision_made",
                     {"tier": tier, "reason": reason, "amount": t["amount"],
                      "contact_attempts_so_far": contact_count}, sb=sb)

        if tier not in ("skip", "manual_review"):
            sb.table("interventions").insert({
                "transaction_id": t["id"],
                "tier": tier,
                "channel": tier,
                "outcome": "pending",
                "notes": reason,
            }).execute()

        counts[tier] = counts.get(tier, 0) + 1
        print(f"{t['id'][:8]}  Rs {float(t['amount']):>10.2f}  {tier:15}  {reason}")

    print("\n--- Summary ---")
    for tier_name in ("auto_retry", "whatsapp", "voice_call", "manual_review", "skip"):
        print(f"{tier_name}: {counts.get(tier_name, 0)}")
    if skipped:
        print(f"left alone (already pending): {skipped}")
    return counts


# --- Local CSV dry run — no Supabase needed ---
def run_with_csv(transactions_path="data/transactions.csv",
                 customers_path="data/customers.csv"):
    with open(customers_path) as f:
        customers = {row["id"]: row for row in csv.DictReader(f)}

    with open(transactions_path) as f:
        transactions = list(csv.DictReader(f))

    contact_counts = {}  # empty on a first run — nobody's been contacted yet

    results = []
    for t in transactions:
        t["segment"] = customers.get(t["customer_id"], {}).get("segment", "b2c_subscription")
        contact_count = contact_counts.get(t["id"], 0)
        tier, reason = decide_tier(t, contact_count)

        if tier == "voice_call" and not within_call_window():
            tier, reason = "whatsapp", "voice tier selected but outside call window — downgraded to WhatsApp"

        results.append((t, tier, reason))
        print(f"{t['id'][:8]}  Rs {float(t['amount']):>10.2f}  {tier:15}  {reason}")

    tiers = [r[1] for r in results]
    print("\n--- Summary ---")
    for tier_name in ("auto_retry", "whatsapp", "voice_call", "manual_review", "skip"):
        print(f"{tier_name}: {tiers.count(tier_name)}")

    return results


if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        run_with_supabase(force=force)
    else:
        print("No SUPABASE_URL / SUPABASE_KEY set — running dry-run against local CSVs.\n")
        run_with_csv()
