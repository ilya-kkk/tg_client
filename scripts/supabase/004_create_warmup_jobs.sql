create table if not exists public.warmup_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    name text not null,
    account_sessions text[] not null,
    mode text not null check (mode in ('cautious', 'normal', 'aggressive')),
    actions_per_day integer not null,
    enabled_actions text[] not null,
    target_channels text[] not null,
    is_active boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists warmup_jobs_user_id_idx
    on public.warmup_jobs (user_id);

create or replace function public.update_warmup_jobs_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_warmup_jobs_updated_at on public.warmup_jobs;
create trigger trg_warmup_jobs_updated_at
before update on public.warmup_jobs
for each row execute function public.update_warmup_jobs_updated_at();

alter table public.warmup_jobs enable row level security;

drop policy if exists warmup_jobs_select_own on public.warmup_jobs;
create policy warmup_jobs_select_own
on public.warmup_jobs
for select
using (auth.uid() = user_id);

drop policy if exists warmup_jobs_insert_own on public.warmup_jobs;
create policy warmup_jobs_insert_own
on public.warmup_jobs
for insert
with check (auth.uid() = user_id);

drop policy if exists warmup_jobs_update_own on public.warmup_jobs;
create policy warmup_jobs_update_own
on public.warmup_jobs
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists warmup_jobs_delete_own on public.warmup_jobs;
create policy warmup_jobs_delete_own
on public.warmup_jobs
for delete
using (auth.uid() = user_id);
