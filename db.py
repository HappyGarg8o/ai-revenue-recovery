"""
db.py — every read and write the agent makes against Supabase, in one place.

Two reasons this module exists rather than each script talking to Supabase
directly:

  1. The audit trail is the deliverable. If `log_audit` is the only way to
     write an audit row, no channel can quietly skip it.
  2. The joined "pending interventions with their transaction and customer"
     query is needed identically by the WhatsApp tier and the voice tier.
"""

import json
from datetime import datetime, timezone

from config import get_supabase


def _jsonable(value):
    """audit_log.payload is jsonb — make sure whatever we hand it survives
    serialisation (datetimes, Decimals from Postgres, etc.)."""
    return json.loads(json.dumps(value, default=str))


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# --- Audit trail -------------------------------------------------------------

def log_audit(transaction_id, event_type, payload, sb=None):
    """Append one row to the audit trail. Never raises past a print — a
    failed audit write should be loud but must not kill a batch run."""
    sb = sb or get_supabase()
    try:
        sb.table("audit_log").insert({
            "transaction_id": transaction_id,
            "event_type": event_type,
            "payload": _jsonable(payload),
        }).execute()
    except Exception as e:  # noqa: BLE001 — audit failures must be visible, not fatal
        print(f"  ! audit_log write failed for {transaction_id}: {e}")


# --- Interventions -----------------------------------------------------------

def fetch_pending_interventions(tier, sb=None):
    """Pending interventions for one tier, with the transaction and customer
    joined in. Ordered oldest-first so a batch run is deterministic."""
    sb = sb or get_supabase()
    return (
        sb.table("interventions")
        .select("*, transactions(*, customers(*))")
        .eq("tier", tier)
        .eq("outcome", "pending")
        .order("fired_at", desc=False)
        .execute()
        .data
    )


def update_intervention(intervention_id, outcome=None, notes=None,
                        promise_to_pay_date=None, sb=None):
    sb = sb or get_supabase()
    patch = {}
    if outcome is not None:
        patch["outcome"] = outcome
    if notes is not None:
        patch["notes"] = notes[:2000]  # notes is text, but keep rows readable
    if promise_to_pay_date is not None:
        patch["promise_to_pay_date"] = promise_to_pay_date
    if not patch:
        return
    sb.table("interventions").update(patch).eq("id", intervention_id).execute()


def mark_blocked(intervention_id, reason, sb=None):
    """Record that a stopping rule refused to let this intervention fire.

    The deployed `interventions_outcome_check` constraint only permits
    'pending' | 'success' | 'failed'. 'skipped' is the honest value and
    migration_add_skipped_outcome.sql adds it, but this must work on the
    schema as deployed today — so try 'skipped' and fall back to 'failed'
    with the rule spelled out in the notes.

    Either way the structured record lives in audit_log as an
    'intervention_skipped' event, which has no constraint and is what the
    dashboard counts. Returns the outcome value actually written.
    """
    try:
        update_intervention(intervention_id, outcome="skipped",
                            notes=f"stopped by rule: {reason}", sb=sb)
        return "skipped"
    except Exception as e:  # noqa: BLE001
        if "outcome_check" not in str(e):
            raise
        update_intervention(intervention_id, outcome="failed",
                            notes=f"stopped by rule: {reason}", sb=sb)
        return "failed"


def interventions_for_transaction(transaction_id, sb=None):
    sb = sb or get_supabase()
    return (
        sb.table("interventions")
        .select("*")
        .eq("transaction_id", transaction_id)
        .order("fired_at", desc=False)
        .execute()
        .data
    )


# An intervention that has not been executed yet has not contacted anybody,
# so it cannot count against the 3-attempt cap. Nor can one the stopping
# rules refused to fire.
NON_CONTACTING_OUTCOMES = {"pending", "skipped"}


def contact_counts(sb=None, contact_tiers=None):
    """transaction_id -> number of times we have actually *contacted* the
    customer about it.

    Two deliberate exclusions:
      - auto_retry is a silent gateway retry with no customer contact, so it
        must not burn one of the 3 permitted attempts.
      - interventions still 'pending' (decided but not yet executed) or
        'skipped' (blocked by a stopping rule) never reached the customer.
    """
    sb = sb or get_supabase()
    if contact_tiers is None:
        from decision_engine import CONTACT_TIERS

        contact_tiers = CONTACT_TIERS
    rows = sb.table("interventions").select("transaction_id, tier, outcome").execute().data
    counts = {}
    for row in rows:
        if row["tier"] in contact_tiers and row["outcome"] not in NON_CONTACTING_OUTCOMES:
            counts[row["transaction_id"]] = counts.get(row["transaction_id"], 0) + 1
    return counts


# --- Transactions ------------------------------------------------------------

def get_transaction(transaction_id, sb=None):
    """Single transaction with its customer, or None. Used for the
    execution-time freshness check — status may have changed since the
    decision was made."""
    sb = sb or get_supabase()
    rows = (
        sb.table("transactions")
        .select("*, customers(*)")
        .eq("id", transaction_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def find_transaction(prefix, sb=None):
    """Resolve a full uuid or a short prefix (what the CLI prints) to one
    transaction. Returns (transaction, error_message)."""
    sb = sb or get_supabase()
    prefix = (prefix or "").strip()
    if not prefix:
        return None, "no transaction id given"

    exact = get_transaction(prefix, sb=sb) if len(prefix) >= 32 else None
    if exact:
        return exact, None

    rows = sb.table("transactions").select("*, customers(*)").execute().data
    matches = [t for t in rows if t["id"].startswith(prefix)]
    if not matches:
        return None, f"no transaction matching '{prefix}'"
    if len(matches) > 1:
        ids = ", ".join(t["id"][:8] for t in matches[:5])
        return None, f"'{prefix}' is ambiguous ({len(matches)} matches: {ids}...)"
    return matches[0], None


def set_transaction_status(transaction_id, status, sb=None):
    sb = sb or get_supabase()
    sb.table("transactions").update({
        "status": status,
        "updated_at": now_iso(),
    }).eq("id", transaction_id).execute()


# --- Metrics -----------------------------------------------------------------

def recovery_metrics(sb=None):
    """The recovery_metrics view from schema.sql, with nulls coalesced —
    total_recovered comes back NULL until at least one transaction is
    marked recovered."""
    sb = sb or get_supabase()
    rows = sb.table("recovery_metrics").select("*").execute().data
    m = dict(rows[0]) if rows else {}
    return {
        "total_transactions": m.get("total_transactions") or 0,
        "total_at_risk": float(m.get("total_at_risk") or 0),
        "total_recovered": float(m.get("total_recovered") or 0),
        "recovered_count": m.get("recovered_count") or 0,
        "recovery_rate_pct": float(m.get("recovery_rate_pct") or 0),
    }
