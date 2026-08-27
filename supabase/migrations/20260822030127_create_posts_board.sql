create table public.posts (
  id uuid primary key default gen_random_uuid(),
  author_id uuid not null references auth.users (id) on delete cascade,
  author_name text not null default '',
  title text not null,
  content text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint posts_title_length check (char_length(title) between 1 and 200),
  constraint posts_content_length check (char_length(content) between 1 and 10000)
);

create index posts_created_at_idx on public.posts (created_at desc);

alter table public.posts enable row level security;

create policy posts_select_authenticated
  on public.posts
  for select
  to authenticated
  using (true);

create policy posts_insert_own
  on public.posts
  for insert
  to authenticated
  with check (auth.uid() = author_id);

create policy posts_update_own
  on public.posts
  for update
  to authenticated
  using (auth.uid() = author_id)
  with check (auth.uid() = author_id);

create policy posts_delete_own
  on public.posts
  for delete
  to authenticated
  using (auth.uid() = author_id);
