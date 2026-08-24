"""
outcome_tracker.py — closes the loop: a customer actually paid.

This is the piece that turns "we fired 40 interventions" into a recovered-
rupee number. `mark_recovered` does three things atomically enough for a
demo:

  1. transactions.status      -> 'recovered'
  2. interventions.outcome    -> 'success' on the intervention that last
                                 touched this transaction (that is the one
                                 that gets credit for the recovery)
  3. audit_log                <- a 'payment_recovered' row with the amount
                                 and the attributed tier

For the demo this is triggered by hand — from the dashboard button or the
CLI below. A real Razorpay `payment.captured` webhook would call exactly
this same function; that listener is a stretch goal, not built here.

Usage:
  python outcome_tracker.py <transaction_id_or_prefix> [more ids...]
  python outcome_tracker.py --list             # show what can be recovered
  python outcome_tracker.py --undo <id>        # put one back to 'failed'
"""

import sys

import db


def mark_recovered(transaction_id, source="manual"):
    """Flip one transaction to recovered. Returns (ok: bool, message: str)."""
    sb = db.get_supabase()

    txn, err = db.find_transaction(transaction_id, sb=sb)
    if err:
        return False, err

    txn_id = txn["id"]
    amount = float(txn["amount"])

    if txn["status"] == "recovered":
        return False, f"{txn_id[:8]} is already marked recovered"

    # Credit the most recent intervention on this transaction.
    interventions = db.interventions_for_transaction(txn_id, sb=sb)
    credited = interventions[-1] if interventions else None

    db.set_transaction_status(txn_id, "recovered", sb=sb)

    if credited:
        db.update_intervention(
            credited["id"],
            outcome="success",
            notes=f"{credited.get('notes') or ''} | payment received "
                  f"(Rs {amount:,.2f}) — recovery attributed to this intervention".strip(" |"),
            sb=sb,
        )

    db.log_audit(txn_id, "payment_recovered", {
        "amount": amount,
        "currency": txn.get("currency", "INR"),
        "attributed_tier": credited["tier"] if credited else None,
        "intervention_id": credited["id"] if credited else None,
        "source": source,
    }, sb=sb)

    tier = credited["tier"] if credited else "no intervention"
    return True, f"{txn_id[:8]}  Rs {amount:,.2f} recovered  (credited to: {tier})"


def undo_recovered(transaction_id):
    """Put a transaction back to 'failed'. Only for resetting the demo
    between practice runs — a real system would never need this."""
    sb = db.get_supabase()

    txn, err = db.find_transaction(transaction_id, sb=sb)
    if err:
        return False, err
    if txn["status"] != "recovered":
        return False, f"{txn['id'][:8]} is not marked recovered"

    db.set_transaction_status(txn["id"], "failed", sb=sb)
    db.log_audit(txn["id"], "recovery_reverted",
                 {"amount": float(txn["amount"]), "source": "manual_undo"}, sb=sb)
    return True, f"{txn['id'][:8]} reverted to 'failed'"


def recoverable_transactions(sb=None):
    """Failed transactions that have had at least one intervention fired —
    i.e. the ones it makes sense to 'pay' during a demo."""
    sb = sb or db.get_supabase()
    rows = (
        sb.table("transactions")
        .select("*, customers(name, segment), interventions(tier, outcome)")
        .eq("status", "failed")
        .order("amount", desc=True)
        .execute()
        .data
    )
    return [r for r in rows if r.get("interventions")]


def _print_list():
    rows = recoverable_transactions()
    if not rows:
        print("Nothing to recover — no failed transactions have interventions.")
        return
    print(f"{'txn':10} {'amount':>12}  {'tier':12} {'outcome':10} customer")
    print("-" * 72)
    for r in rows[:25]:
        iv = r["interventions"][-1]
        customer = (r.get("customers") or {}).get("name", "?")
        print(f"{r['id'][:8]:10} {float(r['amount']):>12,.2f}  "
              f"{iv['tier']:12} {iv['outcome']:10} {customer}")
    if len(rows) > 25:
        print(f"... and {len(rows) - 25} more")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(__doc__)
    elif "--list" in args:
        _print_list()
    elif "--undo" in args:
        for tid in [a for a in args if a != "--undo"]:
            ok, msg = undo_recovered(tid)
            print(("OK   " if ok else "SKIP ") + msg)
    else:
        total = 0.0
        for tid in args:
            ok, msg = mark_recovered(tid, source="cli")
            print(("OK   " if ok else "SKIP ") + msg)
        metrics = db.recovery_metrics()
        print(f"\nRecovered so far: Rs {metrics['total_recovered']:,.2f} "
              f"of Rs {metrics['total_at_risk']:,.2f} at risk "
              f"({metrics['recovery_rate_pct']:.1f}%)")
