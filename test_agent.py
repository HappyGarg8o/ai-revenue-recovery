"""
test_agent.py — the decision engine, the stopping rules, and the dry-run
channels, tested without touching Supabase or any third-party API.

That constraint is the point: a judge can clone this repo with no
credentials at all and still verify that the rules table and the stopping
rules do what the README claims.

    python test_agent.py          # no pytest needed
    pytest test_agent.py -q       # or with pytest, if installed
"""

import tomllib
from datetime import date, datetime, timedelta

import config
import decision_engine as de
import stopping_rules as sr
import voice_caller
import whatsapp_notifier
import auto_retry_executor as auto


# --- helpers -----------------------------------------------------------------

def txn(**over):
    """A failed transaction with sensible defaults; override per test."""
    base = {
        "id": "aaaaaaaa-1111-2222-3333-444444444444",
        "status": "failed",
        "diagnosis_category": "customer_action",
        "amount": 1000.0,
        "attempt_count": 1,
        "segment": "b2c_subscription",
        "failure_reason_code": "card_expired",
    }
    base.update(over)
    return base


# --- the design constraint ---------------------------------------------------

def test_dry_run_defaults_to_true():
    """If this ever flips, a demo run starts messaging real people."""
    assert config.DRY_RUN is True, "DRY_RUN must default to true"


# --- the rules table, one test per rule, in order ----------------------------

def test_rule1_already_resolved_is_skipped():
    tier, reason = de.decide_tier(txn(status="recovered"), 0)
    assert tier == "skip"
    assert "already resolved" in reason


def test_rule2_fraud_never_gets_automated_contact():
    tier, reason = de.decide_tier(txn(diagnosis_category="fraud_risk", amount=50000), 0)
    assert tier == "manual_review"
    assert "fraud" in reason.lower()


def test_rule2_beats_high_value():
    """Fraud is checked before the escalation rules — a big fraud-flagged
    amount must not reach voice_call."""
    tier, _ = de.decide_tier(
        txn(diagnosis_category="fraud_risk", amount=99999, segment="b2b_invoice"), 0)
    assert tier == "manual_review"


def test_rule3_max_contact_attempts_stops_outreach():
    tier, reason = de.decide_tier(txn(), de.MAX_CONTACT_ATTEMPTS)
    assert tier == "manual_review"
    assert str(de.MAX_CONTACT_ATTEMPTS) in reason


def test_rule3_boundary_one_below_cap_still_acts():
    tier, _ = de.decide_tier(txn(), de.MAX_CONTACT_ATTEMPTS - 1)
    assert tier != "manual_review"


def test_rule4_retryable_first_attempt_is_silent_retry():
    tier, reason = de.decide_tier(
        txn(diagnosis_category="retryable", attempt_count=0), 0)
    assert tier == "auto_retry"
    assert "no contact" in reason


def test_rule4_retryable_second_attempt_is_not_retried_silently():
    """attempt_count > 0 means the silent retry already had its chance."""
    tier, _ = de.decide_tier(txn(diagnosis_category="retryable", attempt_count=1), 0)
    assert tier == "whatsapp"


def test_rule5_b2b_high_value_gets_a_call():
    tier, reason = de.decide_tier(
        txn(segment="b2b_invoice", amount=de.HIGH_VALUE_THRESHOLD), 0)
    assert tier == "voice_call"
    assert "B2B" in reason


def test_rule5_b2b_repeat_failure_gets_a_call_even_when_small():
    tier, _ = de.decide_tier(txn(segment="b2b_invoice", amount=100, attempt_count=2), 0)
    assert tier == "voice_call"


def test_rule6_high_value_consumer_gets_a_call():
    tier, reason = de.decide_tier(
        txn(diagnosis_category="customer_action",
            amount=de.HIGH_VALUE_THRESHOLD + 1), 0)
    assert tier == "voice_call"
    assert "call" in reason


def test_rule7_default_is_the_cheap_nudge():
    tier, reason = de.decide_tier(txn(amount=500), 0)
    assert tier == "whatsapp"
    assert "payment link" in reason


def test_every_decision_carries_a_reason():
    """The audit trail is worthless if a tier can arrive without an
    explanation, so no rule may return an empty reason."""
    cases = [
        txn(status="recovered"),
        txn(diagnosis_category="fraud_risk"),
        txn(diagnosis_category="retryable", attempt_count=0),
        txn(segment="b2b_invoice", amount=9000),
        txn(amount=9000),
        txn(amount=100),
    ]
    for t in cases:
        tier, reason = de.decide_tier(t, 0)
        assert reason and len(reason) > 10, f"{tier} returned a thin reason"


# --- contact accounting ------------------------------------------------------

def test_silent_retry_is_not_a_contact_attempt():
    """auto_retry must never burn one of the 3 permitted contacts — it never
    reaches the customer."""
    assert "auto_retry" not in de.CONTACT_TIERS
    assert "whatsapp" in de.CONTACT_TIERS
    assert "voice_call" in de.CONTACT_TIERS


def test_pending_and_blocked_interventions_are_not_contacts():
    import db
    assert "pending" in db.NON_CONTACTING_OUTCOMES
    assert "skipped" in db.NON_CONTACTING_OUTCOMES
    assert "success" not in db.NON_CONTACTING_OUTCOMES


# --- the calling window ------------------------------------------------------

def test_call_window_allows_daytime():
    assert de.within_call_window(datetime(2026, 8, 24, 11, 0))


def test_call_window_blocks_late_night():
    assert not de.within_call_window(datetime(2026, 8, 24, 23, 30))


def test_call_window_blocks_early_morning():
    assert not de.within_call_window(datetime(2026, 8, 24, 6, 0))


def test_call_window_edges():
    assert de.within_call_window(datetime(2026, 8, 24, 9, 0))
    assert de.within_call_window(datetime(2026, 8, 24, 21, 0))
    assert not de.within_call_window(datetime(2026, 8, 24, 21, 1))


def test_voice_outside_window_is_downgraded_not_dropped():
    """decide_tier picks voice; the caller downgrades to whatsapp outside the
    window. Verify the tier the rule chose so the downgrade is meaningful."""
    tier, _ = de.decide_tier(txn(segment="b2b_invoice", amount=9000), 0)
    assert tier == "voice_call"


# --- stopping rules, at execution time --------------------------------------

def test_execution_stops_when_already_paid():
    """The brief's explicit requirement: re-check at execution time."""
    v = sr.check({"tier": "whatsapp"}, {"status": "recovered"}, 0)
    assert v.action == sr.STOP
    assert v.rule == "already_recovered"
    assert not v.allowed


def test_execution_stops_on_written_off():
    v = sr.check({"tier": "whatsapp"}, {"status": "written_off"}, 0)
    assert v.action == sr.STOP
    assert v.rule == "not_failed"


def test_execution_stops_when_transaction_vanished():
    v = sr.check({"tier": "whatsapp"}, None, 0)
    assert v.action == sr.STOP
    assert v.rule == "transaction_missing"


def test_execution_stops_at_the_contact_cap():
    v = sr.check({"tier": "whatsapp"}, {"status": "failed"}, de.MAX_CONTACT_ATTEMPTS)
    assert v.action == sr.STOP
    assert v.rule == "max_contact_attempts"


def test_cap_does_not_block_a_silent_retry():
    """auto_retry is not a contact tier, so the cap must not apply to it."""
    v = sr.check({"tier": "auto_retry"}, {"status": "failed"}, 99)
    assert v.allowed


def test_voice_outside_window_defers_rather_than_failing():
    """DEFER must leave the intervention pending so the next run retries."""
    v = sr.check({"tier": "voice_call"}, {"status": "failed"}, 0,
                 now=datetime(2026, 8, 24, 23, 30))
    assert v.action == sr.DEFER
    assert v.rule == "outside_call_window"
    assert not v.allowed


def test_clean_transaction_is_allowed():
    v = sr.check({"tier": "whatsapp"}, {"status": "failed"}, 0)
    assert v.allowed and v.action == sr.ALLOW


def test_every_verdict_explains_itself():
    verdicts = [
        sr.check({"tier": "whatsapp"}, {"status": "recovered"}, 0),
        sr.check({"tier": "whatsapp"}, None, 0),
        sr.check({"tier": "whatsapp"}, {"status": "failed"}, 3),
        sr.check({"tier": "voice_call"}, {"status": "failed"}, 0,
                 now=datetime(2026, 8, 24, 2, 0)),
    ]
    for v in verdicts:
        assert v.rule and v.reason, f"verdict {v.action} has no explanation"


# --- WhatsApp tier, dry run --------------------------------------------------

def test_whatsapp_dry_run_sends_nothing_and_reports_success():
    ok, detail, payload = whatsapp_notifier.send_nudge(
        "+919999999999", "Test User", 2500.0, "abcd1234-0000")
    assert ok
    assert payload["simulated"] is True
    assert "dry run" in detail
    assert "message_sid" not in payload, "a dry run must not fake a Twilio SID"


def test_whatsapp_body_carries_amount_link_and_optout():
    body = whatsapp_notifier.build_message("Priya", 4649.6, "65c9e2e1-aaaa")
    assert "Priya" in body
    assert "4649.60" in body
    assert "65c9e2e1" in body
    assert "STOP" in body, "an outbound nudge needs an opt-out"


def test_whatsapp_audit_payload_records_what_would_have_gone_out():
    _, _, payload = whatsapp_notifier.send_nudge(
        "+919999999999", "Test User", 100.0, "ffff0000-1111")
    for field in ("to", "from", "body", "payment_link", "amount"):
        assert field in payload, f"audit payload missing {field}"


# --- voice tier, dry run -----------------------------------------------------

def test_voice_dry_run_returns_structure_not_a_transcript():
    ok, result, payload = voice_caller.place_call(
        "+919999999999", "Vikram", 12000.0, "06cc3197-bbbb",
        "bank_timeout", "b2b_invoice")
    assert ok
    assert "transcript" not in result
    for field in ("call_connected", "promise_to_pay", "promise_to_pay_date",
                  "reason_for_delay", "callback_requested", "opt_out_requested"):
        assert field in result, f"structured result missing {field}"


def test_voice_script_is_hinglish_and_names_the_customer():
    ctx = voice_caller.build_call_context(
        "Vikram Patel", 12000.0, "abc12345", "card_expired", "b2b_invoice")
    script = voice_caller.render_prompt(ctx)
    assert "Vikram Patel" in script
    assert "Hinglish" in script
    assert "never threaten" in script, "compliance guardrail missing from script"


def test_voice_simulation_is_deterministic():
    """Same transaction id must always give the same outcome, so a judge
    re-running the batch sees the same numbers."""
    a = voice_caller.simulate_call("06cc3197-bbbb", 1000, "b2b_invoice")
    b = voice_caller.simulate_call("06cc3197-bbbb", 1000, "b2b_invoice")
    assert a == b


def test_voice_simulation_varies_across_transactions():
    outcomes = {voice_caller.simulate_call(f"txn-{i:03d}", 1000, "")["call_connected"]
                for i in range(40)}
    assert outcomes == {True, False}, "simulation should produce both outcomes"


def test_promise_date_is_in_the_future_when_captured():
    for i in range(40):
        r = voice_caller.simulate_call(f"seed-{i}", 1000, "")
        if r["promise_to_pay_date"]:
            assert date.fromisoformat(r["promise_to_pay_date"]) >= date.today()


def test_voice_normalise_survives_garbage_from_a_provider():
    """A provider returning junk must not crash the batch."""
    r = voice_caller._normalise({"promise_to_pay": "yes",
                                 "promise_to_pay_date": "not-a-date",
                                 "call_connected": None})
    assert r["promise_to_pay"] is True
    assert r["promise_to_pay_date"] is None
    assert r["call_connected"] is False


def test_voice_normalise_handles_empty():
    r = voice_caller._normalise(None)
    assert r["call_connected"] is False
    assert r["promise_to_pay_date"] is None


def test_voice_normalise_accepts_a_full_timestamp():
    r = voice_caller._normalise({"promise_to_pay_date": "2026-09-01T10:30:00Z"})
    assert r["promise_to_pay_date"] == "2026-09-01"


def test_voice_summary_reads_as_a_sentence():
    connected = {"call_connected": True, "promise_to_pay": True,
                 "promise_to_pay_date": "2026-09-01"}
    assert "2026-09-01" in voice_caller.summarise(connected)
    assert "no answer" in voice_caller.summarise({"call_connected": False})


# --- auto retry tier ---------------------------------------------------------

def test_auto_retry_simulation_is_deterministic():
    a = auto.simulate_gateway_retry("abc-123")
    b = auto.simulate_gateway_retry("abc-123")
    assert a == b


def test_auto_retry_marks_simulated_and_explains_declines():
    for i in range(40):
        r = auto.simulate_gateway_retry(f"txn-{i}")
        assert r["simulated"] is True
        if not r["captured"]:
            assert r["decline_reason"], "a decline must say why"


def test_auto_retry_capture_rate_is_plausible():
    captures = sum(auto.simulate_gateway_retry(f"t-{i}")["captured"]
                   for i in range(200))
    rate = captures / 200
    assert 0.2 < rate < 0.5, f"capture rate {rate:.0%} looks wrong"


# --- payment link ------------------------------------------------------------

def test_payment_link_is_derived_from_the_transaction():
    link = config.payment_link("65c9e2e1-dead-beef")
    assert link.endswith("65c9e2e1")


# --- theme accessibility -----------------------------------------------------

def _contrast(fg, bg):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def lum(h):
        h = h.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _theme():
    with open(".streamlit/config.toml", "rb") as f:
        return tomllib.load(f)["theme"]


def test_body_text_meets_wcag_aa():
    t = _theme()
    for surface in (t["backgroundColor"], t["secondaryBackgroundColor"]):
        assert _contrast(t["textColor"], surface) >= 4.5


def test_muted_text_meets_wcag_aa():
    t = _theme()
    for surface in (t["backgroundColor"], t["secondaryBackgroundColor"]):
        assert _contrast(t["grayColor"], surface) >= 4.5, \
            "muted text is the usual place dark themes fail"


def test_semantic_colours_meet_wcag_aa():
    t = _theme()
    card = t["secondaryBackgroundColor"]
    for key in ("greenColor", "redColor", "yellowColor", "linkColor"):
        assert _contrast(t[key], card) >= 4.5, f"{key} fails on cards"


def test_control_borders_meet_non_text_contrast():
    """WCAG 1.4.11. On this theme the widget fill barely differs from the
    page, so the border is the only cue that a control is a control."""
    t = _theme()
    for surface in (t["backgroundColor"], t["secondaryBackgroundColor"]):
        assert _contrast(t["borderColor"], surface) >= 3.0


def test_chart_series_are_distinguishable_from_the_card():
    t = _theme()
    card = t["secondaryBackgroundColor"]
    for colour in t["chartCategoricalColors"][:5]:
        assert _contrast(colour, card) >= 3.0


# --- the colour law ----------------------------------------------------------
#
# DESIGN.md reserves green for rupees that actually came back. These tests are
# what stop that from eroding: the contrast tests above pass for almost any
# palette, so on their own they enforce accessibility but not meaning.

def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _is_green(hex_colour):
    r, g, b = _rgb(hex_colour)
    return g > r + 24 and g > b + 24


def _is_blue(hex_colour):
    r, g, b = _rgb(hex_colour)
    return b > r + 24 and b > g + 24


def test_green_is_never_a_button():
    """The whole reason one green can mean 'recovered' is that it means nothing
    else. The moment it becomes the primary colour it is also every button, and
    the meaning is gone."""
    t = _theme()
    assert not _is_green(t["primaryColor"]), \
        "primaryColor is green — buttons would compete with recovered money"
    assert t["primaryColor"] != t["greenColor"]


def test_nothing_in_the_palette_renders_blue():
    """Blue is category camouflage: Razorpay, Growfin and Churnkey are all
    blue-led. Ink instead, so the one green is unmissable."""
    t = _theme()
    for key in ("primaryColor", "linkColor", "blueColor", "textColor"):
        assert not _is_blue(t[key]), f"{key} renders blue"


def test_no_green_in_the_categorical_series():
    """Green labels money on this page, so it must never label a category."""
    t = _theme()
    for colour in t["chartCategoricalColors"]:
        assert not _is_green(colour), f"{colour} would make a category green"


def test_rules_are_set_larger_than_body_text():
    """The rule mechanism. codeFontSize is independent of baseFontSize, which is
    what lets a rule rendered through st.code() outrank body text natively, with
    no CSS injection. If these ever equalise, the inversion is gone."""
    t = _theme()
    code_px = int(str(t["codeFontSize"]).rstrip("px"))
    assert code_px > int(t["baseFontSize"]), \
        "rules must read larger than the prose explaining them"


def test_semantic_colours_meet_wcag_aa_on_the_page_too():
    """The original check only tested cards. Recovered totals and refusal
    reasons are both rendered straight onto the page background, which is the
    warmer of the two surfaces and therefore the one that fails first."""
    t = _theme()
    page = t["backgroundColor"]
    for key in ("greenColor", "redColor", "yellowColor", "grayColor"):
        assert _contrast(t[key], page) >= 4.5, f"{key} fails on the page"


def test_rule_text_is_readable_on_its_own_surface():
    """Rules render on codeBackgroundColor, which is a third surface the other
    contrast tests never look at."""
    t = _theme()
    assert _contrast(t["codeTextColor"], t["codeBackgroundColor"]) >= 4.5


def test_page_texture_does_not_eat_contrast():
    """The dot-grid texture in dashboard.py darkens the page wherever a dot
    lands. Widgets sit on that background, not on a white card, so every
    semantic colour must clear its bar against the DARKEST pixel the texture
    can produce — not against the flat page token.

    This test is what stops someone deepening the texture for looks and
    silently pushing borders or muted text under the bar."""
    import re

    src = open("dashboard.py", encoding="utf-8").read()
    m = re.search(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\s*\)", src)
    assert m, "could not find the texture colour in dashboard.py"
    dot_rgb = tuple(int(m.group(i)) for i in (1, 2, 3))
    dot_alpha = float(m.group(4))
    assert dot_alpha <= 0.06, f"texture alpha {dot_alpha} is too heavy"

    t = _theme()
    page = t["backgroundColor"].lstrip("#")
    page_rgb = tuple(int(page[i:i + 2], 16) for i in (0, 2, 4))
    darkest = "#%02X%02X%02X" % tuple(
        round(page_rgb[i] + (dot_rgb[i] - page_rgb[i]) * dot_alpha) for i in range(3))

    for key, need in (("textColor", 4.5), ("grayColor", 4.5), ("greenColor", 4.5),
                      ("redColor", 4.5), ("yellowColor", 4.5), ("borderColor", 3.0)):
        ratio = _contrast(t[key], darkest)
        assert ratio >= need, (
            f"{key} is {ratio:.2f}:1 on the darkest textured pixel {darkest}, "
            f"needs {need}")


# --- runner ------------------------------------------------------------------

def _main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            failed.append((name, str(e) or "assertion failed"))
        except Exception as e:  # noqa: BLE001
            failed.append((name, f"{type(e).__name__}: {e}"))

    print(f"\n{passed}/{len(tests)} passed")
    for name, err in failed:
        print(f"  FAIL  {name}\n        {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
