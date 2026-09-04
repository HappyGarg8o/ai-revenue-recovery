"""
config.py — one place where the agent reads its environment.

The single most important thing in here is DRY_RUN.

DRY_RUN defaults to TRUE. Every external channel (WhatsApp, voice) checks
it before touching a third-party API. In dry-run the real API call is
skipped and the intervention is instead recorded in `audit_log` with the
exact payload that *would* have gone out, so the audit trail and the
recovery-rate math stay honest without depending on a payment provider's
KYC queue being finished on demo day.

Set DRY_RUN=false (plus real, verified credentials) and the same code
paths make real calls. Nothing else changes.
"""

import os
from functools import lru_cache

try:
    from dotenv import load_dotenv

    load_dotenv()  # picks up a local .env if present; real env vars still win
except ImportError:  # python-dotenv is optional — env vars alone are fine
    pass


_FALSEY = {"false", "0", "no", "off", ""}


def _get(name, default=None):
    """Env var, else st.secrets, else default.

    Streamlit Community Cloud has no .env — secrets are pasted into the
    deploy dialog and surface through st.secrets. Reading both means the
    same code runs locally and hosted with no branch.
    """
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(name, default)
    except Exception:  # noqa: BLE001 — not a Streamlit run, or no secrets file
        return default


def _flag(name, default="true"):
    """Env var -> bool. Anything not explicitly falsey counts as true."""
    return str(_get(name, default)).strip().lower() not in _FALSEY


# --- The design constraint ---------------------------------------------------
DRY_RUN = _flag("DRY_RUN", "true")

# --- Supabase ----------------------------------------------------------------
SUPABASE_URL = _get("SUPABASE_URL")
SUPABASE_KEY = _get("SUPABASE_KEY")

# --- WhatsApp (Twilio) -------------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
# Twilio requires an approved Content Template SID for WhatsApp sends outside
# the 24h session window. Content Templates are gated behind a paid upgrade on
# trial accounts — that is the wall this project hit, and the reason DRY_RUN
# exists. Set this once the account is upgraded and the live path works as-is.
TWILIO_CONTENT_SID = os.environ.get("TWILIO_CONTENT_SID")

# --- Voice ------------------------------------------------------------------
# Bolna is the primary provider (built for Hinglish + Indian telephony).
# Vapi is the fallback. Provider is auto-detected from whichever key is set,
# and can be forced with VOICE_PROVIDER=bolna|vapi.
BOLNA_API_KEY = os.environ.get("BOLNA_API_KEY")
BOLNA_AGENT_ID = os.environ.get("BOLNA_AGENT_ID")
BOLNA_FROM_NUMBER = os.environ.get("BOLNA_FROM_NUMBER")

VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")


def voice_provider():
    """Returns 'bolna' or 'vapi'. Explicit override wins, else whichever
    key is configured, else 'bolna' (dry-run doesn't need a key)."""
    forced = os.environ.get("VOICE_PROVIDER", "").strip().lower()
    if forced in ("bolna", "vapi"):
        return forced
    if BOLNA_API_KEY:
        return "bolna"
    if VAPI_API_KEY:
        return "vapi"
    return "bolna"


# --- Payment link ------------------------------------------------------------
# Stub short-link base. Swap for a real Razorpay Payment Links API call
# (POST /v1/payment_links) when a live gateway is wired in.
PAYMENT_LINK_BASE = os.environ.get("PAYMENT_LINK_BASE", "https://rzp.io/i")


def payment_link(transaction_id):
    return f"{PAYMENT_LINK_BASE}/{str(transaction_id)[:8]}"


@lru_cache(maxsize=1)
def get_supabase():
    """Cached Supabase client. Raises a readable error if creds are missing."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_KEY are not set. Put them in a .env file "
            "next to this script, or export them in your shell."
        )
    from supabase import create_client

    return create_client(SUPABASE_URL, SUPABASE_KEY)


def mode_banner():
    """One-line mode line printed at the top of every runnable script."""
    if DRY_RUN:
        return "MODE: DRY_RUN=true  (no external sends; every action is logged to audit_log)"
    return "MODE: DRY_RUN=false  *** LIVE — real messages and calls will be sent ***"
