create index if not exists ai_comment_jobs_user_id_idx
    on public.ai_comment_jobs (user_id);

create index if not exists ai_comment_job_posts_job_id_created_at_idx
    on public.ai_comment_job_posts (job_id, created_at);
