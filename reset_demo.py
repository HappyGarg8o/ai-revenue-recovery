"""
reset_demo.py — put the batch back to a clean pre-run state.

Each run of `run_pipeline.py` is one recovery *round*: it contacts every
still-failed transaction again, up to the 3-attempt cap. That is correct
dunning behaviour, but after a few practice runs the batch is full of
history and the demo no longer starts from zero.

This clears interventions and audit_log, puts every transaction back to
'failed', and leaves the 15 customers and 40 transactions in place — so
`python run_pipeline.py` gives you a fresh round-one demo.

    python reset_demo.py            # asks first
    python reset_demo.py --yes      # no prompt

Destructive: it deletes the audit trail. Only for demo resets.
"""

import sys

import db


def reset(confirm=True):
    sb = db.get_supabase()

    n_iv = len(sb.table("interventions").select("id").execute().data)
    n_audit = len(sb.table("audit_log").select("id").execute().data)
    recovered = [t for t in sb.table("transactions").select("id")
                 .neq("status", "failed").execute().data]

    print(f"This will delete {n_iv} interventions and {n_audit} audit_log rows, "
          f"and reset {len(recovered)} transaction(s) to 'failed'.")
    print("Customers and transactions themselves are kept.")

    if confirm:
        if input("\nType 'reset' to continue: ").strip().lower() != "reset":
            print("Cancelled.")
            return False

    # audit_log first — it has a FK onto transactions, interventions doesn't
    # cascade into it.
    for table in ("audit_log", "interventions"):
        rows = sb.table(table).select("id").execute().data
        for row in rows:
            sb.table(table).delete().eq("id", row["id"]).execute()
        print(f"  cleared {len(rows)} rows from {table}")

    for t in recovered:
        db.set_transaction_status(t["id"], "failed", sb=sb)
    print(f"  reset {len(recovered)} transaction(s) to 'failed'")

    print("\nDone. Run `python run_pipeline.py` for a fresh round one.")
    return True


if __name__ == "__main__":
    reset(confirm="--yes" not in sys.argv)
