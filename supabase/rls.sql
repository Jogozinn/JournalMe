-- JournalMe Supabase defense-in-depth RLS policies.
-- FastAPI remains the primary authorization layer.
-- Apply only after JournalMe schema is at Alembic head and auth_identities is populated.

begin;

-- SECURITY DEFINER helpers belong in a non-exposed schema.
create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to authenticated, service_role;

create or replace function private.journalme_current_user_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select ai.user_id
  from public.auth_identities ai
  where ai.provider = 'supabase'
    and ai.subject = (select auth.uid())::text
  limit 1;
$$;

create or replace function private.journalme_owns_account(candidate uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.trading_accounts a
    where a.id = candidate
      and a.user_id = (select private.journalme_current_user_id())
  );
$$;

create or replace function private.journalme_owns_trade(candidate uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.trades t
    where t.id = candidate
      and private.journalme_owns_account(t.account_id)
  );
$$;

create or replace function private.journalme_owns_playbook(candidate uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.playbooks p
    where p.id = candidate
      and p.user_id = (select private.journalme_current_user_id())
  );
$$;

create or replace function private.journalme_owns_daily_journal(candidate uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.daily_journals j
    where j.id = candidate
      and private.journalme_owns_account(j.account_id)
  );
$$;

create or replace function private.journalme_owns_profile_version(candidate uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.prop_rule_profile_versions v
    join public.prop_rule_profiles p on p.id = v.profile_id
    where v.id = candidate
      and private.journalme_owns_account(p.account_id)
  );
$$;

-- Functions are not protected by RLS. Only roles that may need the policies
-- should be able to execute these helpers.
revoke execute on function private.journalme_current_user_id() from public;
revoke execute on function private.journalme_owns_account(uuid) from public;
revoke execute on function private.journalme_owns_trade(uuid) from public;
revoke execute on function private.journalme_owns_playbook(uuid) from public;
revoke execute on function private.journalme_owns_daily_journal(uuid) from public;
revoke execute on function private.journalme_owns_profile_version(uuid) from public;

grant execute on function private.journalme_current_user_id() to authenticated, service_role;
grant execute on function private.journalme_owns_account(uuid) to authenticated, service_role;
grant execute on function private.journalme_owns_trade(uuid) to authenticated, service_role;
grant execute on function private.journalme_owns_playbook(uuid) to authenticated, service_role;
grant execute on function private.journalme_owns_daily_journal(uuid) to authenticated, service_role;
grant execute on function private.journalme_owns_profile_version(uuid) to authenticated, service_role;

-- Global catalog tables are not user-owned. They are intentionally read-only
-- to authenticated clients if Data API grants are later enabled.
alter table public.prop_presets enable row level security;
drop policy if exists prop_presets_read on public.prop_presets;
create policy prop_presets_read
on public.prop_presets
for select
to authenticated
using (true);

alter table public.prop_preset_versions enable row level security;
drop policy if exists prop_preset_versions_read on public.prop_preset_versions;
create policy prop_preset_versions_read
on public.prop_preset_versions
for select
to authenticated
using (true);

alter table public.prop_preset_scaling_tiers enable row level security;
drop policy if exists prop_preset_scaling_tiers_read on public.prop_preset_scaling_tiers;
create policy prop_preset_scaling_tiers_read
on public.prop_preset_scaling_tiers
for select
to authenticated
using (true);

-- Direct ownership: users are a JournalMe profile, not a public directory.
alter table public.users enable row level security;
drop policy if exists users_self on public.users;
create policy users_self
on public.users
for all
to authenticated
using (id = (select private.journalme_current_user_id()))
with check (id = (select private.journalme_current_user_id()));

-- Direct-owned tables.
do $$
declare
  t text;
  policy_name text;
begin
  foreach t in array array[
    'trading_accounts',
    'tags',
    'capture_events',
    'playbooks',
    'account_groups',
    'user_preferences',
    'audit_events',
    'import_sessions'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    policy_name := t || '_owner';
    execute format('drop policy if exists %I on public.%I', policy_name, t);
    execute format(
      'create policy %I on public.%I for all to authenticated using (user_id = (select private.journalme_current_user_id())) with check (user_id = (select private.journalme_current_user_id()))',
      policy_name, t
    );
  end loop;
end $$;

-- Account-owned records.
do $$
declare
  t text;
  policy_name text;
begin
  foreach t in array array[
    'trades',
    'fills',
    'orders',
    'cash_transactions',
    'daily_balances',
    'daily_journals',
    'goals',
    'prop_rule_profiles',
    'prop_payout_cycles',
    'prop_payout_records',
    'weekly_reviews',
    'monthly_reviews',
    'manual_adjustments'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    policy_name := t || '_account_owner';
    execute format('drop policy if exists %I on public.%I', policy_name, t);
    execute format(
      'create policy %I on public.%I for all to authenticated using (private.journalme_owns_account(account_id)) with check (private.journalme_owns_account(account_id))',
      policy_name, t
    );
  end loop;
end $$;

-- Child records inherit ownership through their parent.
alter table public.trade_journals enable row level security;
drop policy if exists trade_journals_owner on public.trade_journals;
create policy trade_journals_owner
on public.trade_journals for all to authenticated
using (private.journalme_owns_trade(trade_id))
with check (private.journalme_owns_trade(trade_id));

alter table public.trade_tags enable row level security;
drop policy if exists trade_tags_owner on public.trade_tags;
create policy trade_tags_owner
on public.trade_tags for all to authenticated
using (private.journalme_owns_trade(trade_id))
with check (private.journalme_owns_trade(trade_id));

alter table public.trade_playbooks enable row level security;
drop policy if exists trade_playbooks_owner on public.trade_playbooks;
create policy trade_playbooks_owner
on public.trade_playbooks for all to authenticated
using (private.journalme_owns_trade(trade_id))
with check (private.journalme_owns_trade(trade_id));

alter table public.trade_checklist_responses enable row level security;
drop policy if exists trade_checklist_responses_owner on public.trade_checklist_responses;
create policy trade_checklist_responses_owner
on public.trade_checklist_responses for all to authenticated
using (private.journalme_owns_trade(trade_id))
with check (private.journalme_owns_trade(trade_id));

alter table public.rule_violations enable row level security;
drop policy if exists rule_violations_owner on public.rule_violations;
create policy rule_violations_owner
on public.rule_violations for all to authenticated
using (private.journalme_owns_trade(trade_id))
with check (private.journalme_owns_trade(trade_id));

alter table public.playbook_checklist_items enable row level security;
drop policy if exists playbook_checklist_items_owner on public.playbook_checklist_items;
create policy playbook_checklist_items_owner
on public.playbook_checklist_items for all to authenticated
using (private.journalme_owns_playbook(playbook_id))
with check (private.journalme_owns_playbook(playbook_id));

alter table public.account_group_members enable row level security;
drop policy if exists account_group_members_owner on public.account_group_members;
create policy account_group_members_owner
on public.account_group_members for all to authenticated
using (
  exists (
    select 1
    from public.account_groups g
    where g.id = group_id
      and g.user_id = (select private.journalme_current_user_id())
  )
)
with check (
  exists (
    select 1
    from public.account_groups g
    where g.id = group_id
      and g.user_id = (select private.journalme_current_user_id())
  )
);

alter table public.import_files enable row level security;
drop policy if exists import_files_owner on public.import_files;
create policy import_files_owner
on public.import_files for all to authenticated
using (
  exists (
    select 1
    from public.import_sessions s
    where s.id = import_session_id
      and s.user_id = (select private.journalme_current_user_id())
  )
)
with check (
  exists (
    select 1
    from public.import_sessions s
    where s.id = import_session_id
      and s.user_id = (select private.journalme_current_user_id())
  )
);

alter table public.prop_rule_profile_versions enable row level security;
drop policy if exists prop_rule_profile_versions_owner on public.prop_rule_profile_versions;
create policy prop_rule_profile_versions_owner
on public.prop_rule_profile_versions for all to authenticated
using (
  exists (
    select 1
    from public.prop_rule_profiles p
    where p.id = profile_id
      and private.journalme_owns_account(p.account_id)
  )
)
with check (
  exists (
    select 1
    from public.prop_rule_profiles p
    where p.id = profile_id
      and private.journalme_owns_account(p.account_id)
  )
);

alter table public.prop_scaling_tiers enable row level security;
drop policy if exists prop_scaling_tiers_owner on public.prop_scaling_tiers;
create policy prop_scaling_tiers_owner
on public.prop_scaling_tiers for all to authenticated
using (private.journalme_owns_profile_version(profile_version_id))
with check (private.journalme_owns_profile_version(profile_version_id));

alter table public.attachments enable row level security;
drop policy if exists attachments_owner on public.attachments;
create policy attachments_owner
on public.attachments for all to authenticated
using (
  private.journalme_owns_trade(trade_id)
  or private.journalme_owns_daily_journal(daily_journal_id)
  or private.journalme_owns_playbook(playbook_id)
)
with check (
  private.journalme_owns_trade(trade_id)
  or private.journalme_owns_daily_journal(daily_journal_id)
  or private.journalme_owns_playbook(playbook_id)
);

-- auth_identities is server-managed only. RLS is enabled and no client policy
-- is created, so authenticated/anon clients cannot access it through RLS.
alter table public.auth_identities enable row level security;

commit;
