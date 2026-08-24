-- OPTIONAL migration. The project runs correctly without it.
--
-- The deployed `interventions_outcome_check` allows only
-- 'pending' | 'success' | 'failed'. That means an intervention a stopping
-- rule refused to fire has to be stored as 'failed', which reads the same
-- as a send that genuinely errored. The audit_log 'intervention_skipped'
-- event keeps the two distinguishable, and the dashboard counts blocked
-- interventions from there — but a distinct outcome value is cleaner.
--
-- Run this in the Supabase SQL editor to get it. db.mark_blocked() detects
-- the change automatically; no code edit is needed.

alter table interventions
    drop constraint if exists interventions_outcome_check;

alter table interventions
    add constraint interventions_outcome_check
    check (outcome in ('pending', 'success', 'failed', 'skipped'));
