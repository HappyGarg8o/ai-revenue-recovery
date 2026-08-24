"""
whatsapp_notifier.py — fires the WhatsApp recovery tier.

Runs in one of two modes, controlled by the DRY_RUN env var (default true):

  DRY_RUN=true   Nothing leaves the building. The exact message that would
                 have been sent is written to audit_log as a
                 'whatsapp_dry_run' event, and the intervention is marked
                 'success' so recovery-rate math still works for the demo.

  DRY_RUN=false  The real Twilio path below runs, unchanged.

Why the flag exists: Twilio requires an approved Content Template
(`ContentSid`) for WhatsApp sends outside the 24-hour session window, and
Content Templates are gated behind a paid account upgrade — confirmed by
live testing, not a misconfiguration. The demo must not depend on a
third-party KYC queue finishing on time. Set TWILIO_CONTENT_SID and
DRY_RUN=false on an upgraded account and this file sends for real.

Usage:
  python whatsapp_notifier.py                      # batch over pending interventions
  python whatsapp_notifier.py --test +91XXXXXXXXXX "Test Name" 999.00 txn123
"""

import sys

import config
import db
import stopping_rules


def build_message(customer_name, amount, transaction_id):
    link = config.payment_link(transaction_id)
    return (
        f"Hi {customer_name}, your recent payment of Rs {amount:.2f} didn't go through. "
        f"Pay securely here to keep your order/subscription active: {link}\n\n"
        f"Reply STOP to opt out."
    )


def _twilio_client():
    """Built lazily and only on the live path, so dry-run needs no Twilio
    credentials at all."""
    from twilio.rest import Client

    if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
        raise RuntimeError(
            "DRY_RUN=false but TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are not set."
        )
    return Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)


def send_nudge(to_phone, customer_name, amount, transaction_id):
    """Sends one WhatsApp nudge, or simulates it under DRY_RUN.

    Returns (success: bool, detail: str, payload: dict). `payload` is what
    goes into the audit trail — under DRY_RUN it is the full record of what
    would have gone out.
    """
    body = build_message(customer_name, amount, transaction_id)
    payload = {
        "to": f"whatsapp:{to_phone}",
        "from": config.TWILIO_WHATSAPP_FROM,
        "body": body,
        "payment_link": config.payment_link(transaction_id),
        "customer_name": customer_name,
        "amount": amount,
    }

    if config.DRY_RUN:
        payload["simulated"] = True
        return True, "dry run — message composed, not sent", payload

    # --- live path ---------------------------------------------------------
    try:
        client = _twilio_client()
        kwargs = {
            "from_": config.TWILIO_WHATSAPP_FROM,
            "to": f"whatsapp:{to_phone}",
        }
        if config.TWILIO_CONTENT_SID:
            # Templated send — required outside the 24h session window.
            kwargs["content_sid"] = config.TWILIO_CONTENT_SID
            kwargs["content_variables"] = _content_variables(
                customer_name, amount, transaction_id
            )
            payload["content_sid"] = config.TWILIO_CONTENT_SID
        else:
            kwargs["body"] = body

        message = client.messages.create(**kwargs)
        payload["message_sid"] = message.sid
        return True, message.sid, payload
    except Exception as e:  # noqa: BLE001 — one bad number must not kill the batch
        payload["error"] = str(e)
        return False, str(e), payload


def _content_variables(customer_name, amount, transaction_id):
    """Twilio Content Template variables, JSON-encoded. Positional keys
    match a template body of:
      "Hi {{1}}, your payment of Rs {{2}} didn't go through. Pay here: {{3}}"
    """
    import json

    return json.dumps({
        "1": customer_name,
        "2": f"{amount:.2f}",
        "3": config.payment_link(transaction_id),
    })


def run_batch():
    print(config.mode_banner())
    print("Tier: whatsapp\n")

    sb = db.get_supabase()
    pending = db.fetch_pending_interventions("whatsapp", sb=sb)
    if not pending:
        print("No pending WhatsApp interventions found.")
        return {"sent": 0, "failed": 0, "skipped": 0}

    counts = {"sent": 0, "failed": 0, "skipped": 0}
    contacts = db.contact_counts(sb=sb)

    for iv in pending:
        txn_id = iv["transaction_id"]

        # Re-read the transaction — status may have changed since the
        # decision was made. This is the execution-time stopping-rule check.
        txn = db.get_transaction(txn_id, sb=sb)
        verdict = stopping_rules.check(iv, txn, contacts.get(txn_id, 0))

        if not verdict.allowed:
            db.log_audit(txn_id, "intervention_skipped", {
                "tier": "whatsapp",
                "rule": verdict.rule,
                "reason": verdict.reason,
                "action": verdict.action,
            }, sb=sb)
            if verdict.action == stopping_rules.STOP:
                db.mark_blocked(iv["id"], verdict.reason, sb=sb)
            counts["skipped"] += 1
            print(f"{txn_id[:8]}  {'SKIPPED':10}  {verdict.reason}")
            continue

        customer = txn.get("customers") or {}
        success, detail, payload = send_nudge(
            to_phone=customer.get("phone", ""),
            customer_name=customer.get("name", "there"),
            amount=float(txn["amount"]),
            transaction_id=txn_id,
        )

        if config.DRY_RUN:
            event = "whatsapp_dry_run"
        else:
            event = "whatsapp_sent" if success else "whatsapp_failed"

        db.log_audit(txn_id, event, payload, sb=sb)
        db.update_intervention(iv["id"],
                               outcome="success" if success else "failed",
                               notes=detail, sb=sb)

        # This send counts as a contact attempt from here on.
        if success:
            contacts[txn_id] = contacts.get(txn_id, 0) + 1

        counts["sent" if success else "failed"] += 1
        label = "DRY RUN" if config.DRY_RUN else ("sent" if success else "FAILED")
        print(f"{txn_id[:8]}  {customer.get('phone', '?'):15}  {label:10}  {detail[:60]}")

    print(f"\n--- Summary ---\nsent: {counts['sent']}  "
          f"failed: {counts['failed']}  skipped by stopping rules: {counts['skipped']}")
    return counts


if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        phone, name, amount, txn_id = sys.argv[idx + 1: idx + 5]
        print(config.mode_banner())
        ok, detail, payload = send_nudge(phone, name, float(amount), txn_id)
        print(f"{'OK' if ok else 'FAILED'}: {detail}")
        if config.DRY_RUN:
            print(f"\nWould have sent:\n{payload['body']}")
    else:
        run_batch()
