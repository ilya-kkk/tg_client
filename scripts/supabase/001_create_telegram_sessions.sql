create table if not exists public.telegram_sessions (
    session_id text primary key,
    phone text,
    string_session text,
    phone_code_hash text,
    is_authorized boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists set_telegram_sessions_updated_at on public.telegram_sessions;
create trigger set_telegram_sessions_updated_at
before update on public.telegram_sessions
for each row
execute function public.set_updated_at();

alter table public.telegram_sessions enable row level security;

drop policy if exists telegram_sessions_select on public.telegram_sessions;
create policy telegram_sessions_select
on public.telegram_sessions
for select
using (true);

drop policy if exists telegram_sessions_insert on public.telegram_sessions;
create policy telegram_sessions_insert
on public.telegram_sessions
for insert
with check (true);

drop policy if exists telegram_sessions_update on public.telegram_sessions;
create policy telegram_sessions_update
on public.telegram_sessions
for update
using (true)
with check (true);

drop policy if exists telegram_sessions_delete on public.telegram_sessions;
create policy telegram_sessions_delete
on public.telegram_sessions
for delete
using (true);
