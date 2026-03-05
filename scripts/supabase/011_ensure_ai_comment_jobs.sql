create extension if not exists pgcrypto;

create table if not exists public.ai_comment_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id),
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
