"""
run_pipeline.py — the whole agent, end to end, in one command.

    python run_pipeline.py

Runs the four stages in cost order, which is the same order a judge should
read them in:

    1. decide      every failed transaction gets a tier + a one-sentence
                   reason, both written to audit_log
    2. auto_retry  silent gateway re-presentment, no customer contact
    3. whatsapp    low-cost templated nudge with a payment link
    4. voice_call  Hinglish promise-to-pay call, structured result captured

Every stage re-checks the stopping rules immediately before it fires
anything, and every stage honours DRY_RUN (default true).

Flags:
    --force        re-decide transactions that already have a pending
                   intervention (default: leave them alone, so running this
                   twice never double-contacts anyone)
    --skip-decide  execute pending interventions only
"""

import sys
import time

import config
import db


def _rule(title):
    print("\n" + "=" * 74)
    print(f"  {title}")
    print("=" * 74)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv
    skip_decide = "--skip-decide" in argv

    started = time.time()

    print("=" * 74)
    print("  AI REVENUE RECOVERY AGENT — full pipeline")
    print("=" * 74)
    print(f"  {config.mode_banner()}")
    print(f"  Voice provider: {config.voice_provider()}")

    before = db.recovery_metrics()
    print(f"  At risk before run: Rs {before['total_at_risk']:,.2f} "
          f"across {before['total_transactions']} transactions")
    print(f"  Already recovered:  Rs {before['total_recovered']:,.2f} "
          f"({before['recovery_rate_pct']:.1f}%)")

    if not skip_decide:
        _rule("STAGE 1 / 4 — decision engine")
        import decision_engine
        decision_engine.run_with_supabase(force=force)

    _rule("STAGE 2 / 4 — auto_retry (silent gateway retry)")
    import auto_retry_executor
    auto_retry_executor.run_batch()

    _rule("STAGE 3 / 4 — whatsapp (templated nudge + payment link)")
    import whatsapp_notifier
    whatsapp_notifier.run_batch()

    _rule("STAGE 4 / 4 — voice_call (Hinglish promise-to-pay)")
    import voice_caller
    voice_caller.run_batch()

    after = db.recovery_metrics()
    _rule("RESULT")
    print(f"  Transactions in batch : {after['total_transactions']}")
    print(f"  Total at risk         : Rs {after['total_at_risk']:,.2f}")
    print(f"  Recovered             : Rs {after['total_recovered']:,.2f} "
          f"({after['recovered_count']} transactions)")
    print(f"  Recovery rate         : {after['recovery_rate_pct']:.1f}%")
    delta = after["total_recovered"] - before["total_recovered"]
    if delta:
        print(f"  Recovered this run    : Rs {delta:,.2f}")
    print(f"\n  Ran in {time.time() - started:.1f}s. "
          f"Every decision and send is in audit_log.")
    print("  Dashboard: python -m streamlit run dashboard.py")


if __name__ == "__main__":
    main()
