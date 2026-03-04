create table if not exists public.ai_comment_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    name text not null,
    account_sessions text[] not null,
    target_channels text[] not null,
    user_prompt text not null,
    system_prompt text not null,
    is_active boolean not null default false,
    last_checked_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create or replace function public.update_ai_comment_jobs_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_ai_comment_jobs_updated_at on public.ai_comment_jobs;
create trigger trg_ai_comment_jobs_updated_at
before update on public.ai_comment_jobs
for each row execute function public.update_ai_comment_jobs_updated_at();
