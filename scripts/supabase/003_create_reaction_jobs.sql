create table if not exists public.reaction_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    account_sessions text[] not null,
    reactions text[] not null,
    message_frequency text not null check (message_frequency in ('every', '1/2', '1/3', '2/3')),
    target_chats text[] not null,
    is_active boolean not null default false,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists reaction_jobs_user_id_idx
    on public.reaction_jobs (user_id);

create or replace function public.update_reaction_jobs_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = timezone('utc', now());
    return new;
end;
$$;

drop trigger if exists trg_reaction_jobs_updated_at on public.reaction_jobs;
create trigger trg_reaction_jobs_updated_at
before update on public.reaction_jobs
for each row execute function public.update_reaction_jobs_updated_at();

alter table public.reaction_jobs enable row level security;

drop policy if exists reaction_jobs_select_own on public.reaction_jobs;
create policy reaction_jobs_select_own
on public.reaction_jobs
for select
using (auth.uid() = user_id or auth.role() = 'service_role');

drop policy if exists reaction_jobs_insert_own on public.reaction_jobs;
create policy reaction_jobs_insert_own
on public.reaction_jobs
for insert
with check (auth.uid() = user_id or auth.role() = 'service_role');

drop policy if exists reaction_jobs_update_own on public.reaction_jobs;
create policy reaction_jobs_update_own
on public.reaction_jobs
for update
using (auth.uid() = user_id or auth.role() = 'service_role')
with check (auth.uid() = user_id or auth.role() = 'service_role');

drop policy if exists reaction_jobs_delete_own on public.reaction_jobs;
create policy reaction_jobs_delete_own
on public.reaction_jobs
for delete
using (auth.uid() = user_id or auth.role() = 'service_role');
