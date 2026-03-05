create table if not exists public.ai_comment_job_posts (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null
        references public.ai_comment_jobs(id) on delete cascade,
    channel_id text not null,
    message_id bigint not null,
    comment_message_id bigint,
    status text not null
        check (status in ('posted', 'skipped', 'failed')),
    error text,
    created_at timestamptz not null default now()
);

create unique index if not exists ai_comment_job_posts_job_channel_message_uidx
    on public.ai_comment_job_posts (job_id, channel_id, message_id);
