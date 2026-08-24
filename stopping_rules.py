"""
stopping_rules.py — the guard every intervention passes through immediately
before it fires.

The decision engine already applies stopping rules at *decision* time. This
module re-applies them at *execution* time, which is a different moment and
can produce a different answer: a customer may have paid, or been contacted
by another tier, in between. The brief calls this out explicitly — check
`status == 'recovered'` at execution time, not just decision time.

Outcomes:
  ALLOW   -> fire the intervention
  STOP    -> do not fire, terminal. Intervention is marked 'skipped'.
  DEFER   -> do not fire, but try again on the next run (outside the call
             window). Intervention stays 'pending'.

Every non-ALLOW result is written to audit_log by the caller, so a judge can
see the rule that fired and why.
"""

from decision_engine import (
    CONTACT_TIERS,
    MAX_CONTACT_ATTEMPTS,
    within_call_window,
)

ALLOW = "allow"
STOP = "stop"
DEFER = "defer"


class Verdict:
    """(action, rule, reason) — `rule` is the short machine name for the
    audit log, `reason` is the one sentence a human reads."""

    def __init__(self, action, rule="", reason=""):
        self.action = action
        self.rule = rule
        self.reason = reason

    @property
    def allowed(self):
        return self.action == ALLOW

    def __repr__(self):
        return f"<Verdict {self.action} {self.rule}: {self.reason}>"


def check(intervention, transaction, prior_contacts, now=None):
    """Returns a Verdict. `transaction` must be freshly read from the
    database, not the copy the decision engine saw — that is the whole
    point of this check.

    `prior_contacts` counts customer-contact interventions on this
    transaction that have already been executed (see db.contact_counts).
    """
    tier = intervention.get("tier")

    if transaction is None:
        return Verdict(STOP, "transaction_missing",
                       "transaction no longer exists — nothing to recover")

    status = transaction.get("status")

    # Rule 1 — the brief's explicit requirement. Recovered between decision
    # and execution: never contact a customer who has already paid.
    if status == "recovered":
        return Verdict(STOP, "already_recovered",
                       "transaction was already recovered before this intervention fired")

    # Rule 2 — any other non-failed status means it left the recovery funnel.
    if status != "failed":
        return Verdict(STOP, "not_failed",
                       f"transaction status is '{status}', not 'failed' — out of scope for recovery")

    # Rule 3 — hard cap on how many times one transaction may be chased.
    if tier in CONTACT_TIERS and prior_contacts >= MAX_CONTACT_ATTEMPTS:
        return Verdict(STOP, "max_contact_attempts",
                       f"stopping rule: {MAX_CONTACT_ATTEMPTS} contact attempts already made")

    # Rule 4 — TRAI-aligned calling window. Not terminal: try again later.
    if tier == "voice_call" and not within_call_window(now):
        return Verdict(DEFER, "outside_call_window",
                       "outside the 9am-9pm calling window — deferred to the next run")

    return Verdict(ALLOW, "cleared", "all stopping rules cleared")
