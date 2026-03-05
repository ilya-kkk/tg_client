alter table public.ai_comment_jobs enable row level security;

drop policy if exists ai_comment_jobs_select_own on public.ai_comment_jobs;
create policy ai_comment_jobs_select_own
on public.ai_comment_jobs
for select
using (auth.uid() = user_id);

drop policy if exists ai_comment_jobs_insert_own on public.ai_comment_jobs;
create policy ai_comment_jobs_insert_own
on public.ai_comment_jobs
for insert
with check (auth.uid() = user_id);

drop policy if exists ai_comment_jobs_update_own on public.ai_comment_jobs;
create policy ai_comment_jobs_update_own
on public.ai_comment_jobs
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists ai_comment_jobs_delete_own on public.ai_comment_jobs;
create policy ai_comment_jobs_delete_own
on public.ai_comment_jobs
for delete
using (auth.uid() = user_id);

alter table public.ai_comment_job_posts enable row level security;

drop policy if exists ai_comment_job_posts_select_own on public.ai_comment_job_posts;
create policy ai_comment_job_posts_select_own
on public.ai_comment_job_posts
for select
using (
    exists (
        select 1
        from public.ai_comment_jobs
        where public.ai_comment_jobs.id = public.ai_comment_job_posts.job_id
          and public.ai_comment_jobs.user_id = auth.uid()
    )
);

drop policy if exists ai_comment_job_posts_insert_own on public.ai_comment_job_posts;
create policy ai_comment_job_posts_insert_own
on public.ai_comment_job_posts
for insert
with check (
    exists (
        select 1
        from public.ai_comment_jobs
        where public.ai_comment_jobs.id = public.ai_comment_job_posts.job_id
          and public.ai_comment_jobs.user_id = auth.uid()
    )
);

drop policy if exists ai_comment_job_posts_update_own on public.ai_comment_job_posts;
create policy ai_comment_job_posts_update_own
on public.ai_comment_job_posts
for update
using (
    exists (
        select 1
        from public.ai_comment_jobs
        where public.ai_comment_jobs.id = public.ai_comment_job_posts.job_id
          and public.ai_comment_jobs.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.ai_comment_jobs
        where public.ai_comment_jobs.id = public.ai_comment_job_posts.job_id
          and public.ai_comment_jobs.user_id = auth.uid()
    )
);

drop policy if exists ai_comment_job_posts_delete_own on public.ai_comment_job_posts;
create policy ai_comment_job_posts_delete_own
on public.ai_comment_job_posts
for delete
using (
    exists (
        select 1
        from public.ai_comment_jobs
        where public.ai_comment_jobs.id = public.ai_comment_job_posts.job_id
          and public.ai_comment_jobs.user_id = auth.uid()
    )
);
