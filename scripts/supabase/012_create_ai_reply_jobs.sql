create table if not exists public.ai_reply_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    name text not null,
    account_sessions text[] not null default '{}'::text[],
    target_chats text[] not null default '{}'::text[],
    triggers text[] not null default '{}'::text[],
    reply_prompt text not null,
    is_active boolean not null default false,
    last_checked_at timestamptz null,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.ai_reply_job_messages (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references public.ai_reply_jobs(id) on delete cascade,
    chat_id text not null,
    chat_name text null,
    message_id bigint not null,
    sender_id bigint null,
    message_text text null,
    message_date timestamptz null,
    matched_trigger text null,
    reply_message_id bigint null,
    reply_text text null,
    processed_session_id text null,
    status text not null,
    error text null,
    created_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists ai_reply_job_messages_job_chat_message_uidx
    on public.ai_reply_job_messages(job_id, chat_id, message_id);

create index if not exists ai_reply_jobs_user_id_idx
    on public.ai_reply_jobs(user_id);

create index if not exists ai_reply_job_messages_job_id_created_at_idx
    on public.ai_reply_job_messages(job_id, created_at desc);

create or replace function public.set_ai_reply_jobs_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = timezone('utc', now());
    return new;
end;
$$;

drop trigger if exists set_ai_reply_jobs_updated_at on public.ai_reply_jobs;

create trigger set_ai_reply_jobs_updated_at
before update on public.ai_reply_jobs
for each row
execute function public.set_ai_reply_jobs_updated_at();

alter table public.ai_reply_jobs enable row level security;
alter table public.ai_reply_job_messages enable row level security;

drop policy if exists ai_reply_jobs_select_own on public.ai_reply_jobs;
create policy ai_reply_jobs_select_own
on public.ai_reply_jobs
for select
using (auth.role() = 'service_role' or auth.uid() = user_id);

drop policy if exists ai_reply_jobs_insert_own on public.ai_reply_jobs;
create policy ai_reply_jobs_insert_own
on public.ai_reply_jobs
for insert
with check (auth.role() = 'service_role' or auth.uid() = user_id);

drop policy if exists ai_reply_jobs_update_own on public.ai_reply_jobs;
create policy ai_reply_jobs_update_own
on public.ai_reply_jobs
for update
using (auth.role() = 'service_role' or auth.uid() = user_id)
with check (auth.role() = 'service_role' or auth.uid() = user_id);

drop policy if exists ai_reply_jobs_delete_own on public.ai_reply_jobs;
create policy ai_reply_jobs_delete_own
on public.ai_reply_jobs
for delete
using (auth.role() = 'service_role' or auth.uid() = user_id);

drop policy if exists ai_reply_job_messages_select_own on public.ai_reply_job_messages;
create policy ai_reply_job_messages_select_own
on public.ai_reply_job_messages
for select
using (
    auth.role() = 'service_role'
    or exists (
        select 1
        from public.ai_reply_jobs jobs
        where jobs.id = ai_reply_job_messages.job_id
          and jobs.user_id = auth.uid()
    )
);

drop policy if exists ai_reply_job_messages_insert_own on public.ai_reply_job_messages;
create policy ai_reply_job_messages_insert_own
on public.ai_reply_job_messages
for insert
with check (
    auth.role() = 'service_role'
    or exists (
        select 1
        from public.ai_reply_jobs jobs
        where jobs.id = ai_reply_job_messages.job_id
          and jobs.user_id = auth.uid()
    )
);

drop policy if exists ai_reply_job_messages_update_own on public.ai_reply_job_messages;
create policy ai_reply_job_messages_update_own
on public.ai_reply_job_messages
for update
using (
    auth.role() = 'service_role'
    or exists (
        select 1
        from public.ai_reply_jobs jobs
        where jobs.id = ai_reply_job_messages.job_id
          and jobs.user_id = auth.uid()
    )
)
with check (
    auth.role() = 'service_role'
    or exists (
        select 1
        from public.ai_reply_jobs jobs
        where jobs.id = ai_reply_job_messages.job_id
          and jobs.user_id = auth.uid()
    )
);

drop policy if exists ai_reply_job_messages_delete_own on public.ai_reply_job_messages;
create policy ai_reply_job_messages_delete_own
on public.ai_reply_job_messages
for delete
using (
    auth.role() = 'service_role'
    or exists (
        select 1
        from public.ai_reply_jobs jobs
        where jobs.id = ai_reply_job_messages.job_id
          and jobs.user_id = auth.uid()
    )
);
