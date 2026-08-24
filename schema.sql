-- schema.sql — Supabase/Postgres schema for the AI Revenue Recovery Agent.
--
-- NOTE: this file was reconstructed from the live Supabase project (it was
-- missing from the working directory). It matches the deployed tables,
-- columns and the recovery_metrics view exactly, including the fact that
-- recovery_rate_pct is measured by transaction COUNT, not by value.
--
-- Safe to re-run: everything is IF NOT EXISTS / CREATE OR REPLACE.

create extension if not exists "pgcrypto";

-- --------------------------------------------------------------------------
-- customers
-- --------------------------------------------------------------------------
create table if not exists customers (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    phone       text,
    email       text,
    -- 'b2c_subscription' | 'b2b_invoice' — drives the voice-tier rule
    segment     text not null default 'b2c_subscription',
    -- 'low' | 'mid' | 'high'
    ltv_tier    text not null default 'low',
    created_at  timestamptz not null default now()
);

-- --------------------------------------------------------------------------
-- transactions — the failed/at-risk payments the agent works on
-- --------------------------------------------------------------------------
create table if not exists transactions (
    id                  uuid primary key default gen_random_uuid(),
    customer_id         uuid references customers (id) on delete cascade,
    amount              numeric(12, 2) not null,
    currency            text not null default 'INR',
    -- raw gateway code: insufficient_funds, card_expired, bank_timeout, ...
    failure_reason_code text,
    -- the diagnosis: 'customer_action' | 'retryable' | 'fraud_risk'
    diagnosis_category  text,
    attempt_count       integer not null default 0,
    status              text not null default 'failed'
        constraint transactions_status_check
        check (status in ('failed', 'recovered', 'written_off')),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists transactions_status_idx on transactions (status);
create index if not exists transactions_customer_idx on transactions (customer_id);

-- --------------------------------------------------------------------------
-- interventions — one row per recovery action the agent decided to take
-- --------------------------------------------------------------------------
create table if not exists interventions (
    id                  uuid primary key default gen_random_uuid(),
    transaction_id      uuid references transactions (id) on delete cascade,
    tier                text not null
        constraint interventions_tier_check
        check (tier in ('auto_retry', 'whatsapp', 'voice_call')),
    channel             text,
    fired_at            timestamptz not null default now(),
    --   pending = decided, not yet executed
    --   success = executed (in DRY_RUN: composed and audited, not delivered)
    --   failed  = the send errored, OR a stopping rule blocked it
    -- See migration_add_skipped_outcome.sql to add a distinct 'skipped'
    -- value. The code works with or without that migration; either way the
    -- authoritative record of a blocked intervention is the
    -- 'intervention_skipped' event in audit_log.
    outcome             text not null default 'pending'
        constraint interventions_outcome_check
        check (outcome in ('pending', 'success', 'failed')),
    -- structured result of the voice tier's promise-to-pay flow
    promise_to_pay_date date,
    notes               text
);

create index if not exists interventions_txn_idx on interventions (transaction_id);
create index if not exists interventions_tier_outcome_idx on interventions (tier, outcome);

-- --------------------------------------------------------------------------
-- audit_log — append-only. This table IS the compliance deliverable.
-- Every decision, every send, every stopping rule that fired, every
-- recovery. Nothing is ever updated or deleted here.
-- --------------------------------------------------------------------------
create table if not exists audit_log (
    id             uuid primary key default gen_random_uuid(),
    transaction_id uuid references transactions (id) on delete cascade,
    -- decision_made | auto_retry_dry_run | whatsapp_dry_run | voice_dry_run
    -- | whatsapp_sent | whatsapp_failed | voice_call_completed
    -- | voice_call_failed | intervention_skipped | payment_recovered
    -- | recovery_reverted
    event_type     text not null,
    payload        jsonb,
    created_at     timestamptz not null default now()
);

create index if not exists audit_log_txn_idx on audit_log (transaction_id);
create index if not exists audit_log_created_idx on audit_log (created_at desc);

-- --------------------------------------------------------------------------
-- recovery_metrics — the headline numbers, in one row.
--
-- recovery_rate_pct is COUNT-based (recovered transactions / total
-- transactions). The dashboard also shows a value-weighted rate alongside
-- it, because the two differ whenever recovered transactions are larger or
-- smaller than average.
-- --------------------------------------------------------------------------
create or replace view recovery_metrics as
select
    count(*)                                                        as total_transactions,
    sum(amount)                                                     as total_at_risk,
    sum(amount) filter (where status = 'recovered')                 as total_recovered,
    count(*) filter (where status = 'recovered')                    as recovered_count,
    round(
        count(*) filter (where status = 'recovered') * 100.0
        / nullif(count(*), 0)
    , 2)                                                            as recovery_rate_pct
from transactions;
