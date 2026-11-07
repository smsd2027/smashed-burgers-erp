create table if not exists public.erp_state (
  id text primary key check (id = 'main'),
  v bigint not null default 0,
  data jsonb not null default '{}'::jsonb,
  users jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.erp_state enable row level security;
revoke all on public.erp_state from anon, authenticated;

-- Stamp the update time only. The server owns the version number (v).
create or replace function public.erp_state_touch() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists erp_state_touch on public.erp_state;
create trigger erp_state_touch before update on public.erp_state
for each row execute function public.erp_state_touch();

-- Seed the singleton row
insert into public.erp_state (id) values ('main') on conflict (id) do nothing;

-- Private image bucket
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('erp-images', 'erp-images', false, 6291456, array['image/jpeg'])
on conflict (id) do update set public = false, file_size_limit = 6291456,
  allowed_mime_types = array['image/jpeg'];
