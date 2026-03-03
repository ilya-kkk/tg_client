create extension if not exists pg_trgm;

create table if not exists public.parsed_channels (
    id bigint generated always as identity primary key,
    session_id text not null,
    channel_id text not null,
    title text not null,
    username text,
    link text,
    about text,
    participants_count integer,
    verified boolean,
    scam boolean,
    fake boolean,
    found_by jsonb not null default '[]'::jsonb,
    last_seen_at timestamptz not null default timezone('utc', now()),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    constraint parsed_channels_session_channel_unique unique (session_id, channel_id)
);

create index if not exists parsed_channels_session_idx
    on public.parsed_channels (session_id);

create index if not exists parsed_channels_username_idx
    on public.parsed_channels (username);

create index if not exists parsed_channels_title_trgm_idx
    on public.parsed_channels using gin (title gin_trgm_ops);

create index if not exists parsed_channels_found_by_gin_idx
    on public.parsed_channels using gin (found_by);

create or replace function public.update_parsed_channels_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = timezone('utc', now());
    new.last_seen_at = timezone('utc', now());
    return new;
end;
$$;

drop trigger if exists trg_parsed_channels_updated_at on public.parsed_channels;
create trigger trg_parsed_channels_updated_at
before update on public.parsed_channels
for each row execute function public.update_parsed_channels_updated_at();
