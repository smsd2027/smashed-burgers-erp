-- Run this entire script once in Supabase > SQL Editor > New query.
-- The ERP backend uses its server-only Supabase secret key; do not put that key in HTML.
create table if not exists public.erp_state (
  id text primary key check (id = 'main'),
  v bigint not null default 0,
  data jsonb,
  users jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.erp_state enable row level security;

-- Private image storage for customer review screenshots.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('erp-images', 'erp-images', false, 6291456, array['image/jpeg'])
on conflict (id) do update set public = false, file_size_limit = 6291456,
  allowed_mime_types = array['image/jpeg'];
