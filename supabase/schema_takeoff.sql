create table if not exists public.takeoff_runs (
  id bigint generated always as identity primary key,
  project_id text not null,
  source_name text not null,
  confidence double precision not null default 0,
  scale_label text,
  walls_count integer not null default 0,
  rooms_count integer not null default 0,
  doors_count integer not null default 0,
  windows_count integer not null default 0,
  fixtures_count integer not null default 0,
  walls_lf double precision not null default 0,
  rooms_sf double precision not null default 0,
  payload_json jsonb not null default '{}'::jsonb,
  audit_id text,
  created_at timestamptz not null default now()
);

create table if not exists public.chat_logs (
  id bigint generated always as identity primary key,
  project_id text not null,
  user_text text not null,
  assistant_text text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.schedules (
  id bigint generated always as identity primary key,
  project_id text not null,
  title text not null,
  starts_at timestamptz not null,
  notes text,
  updated_at timestamptz not null default now()
);

create index if not exists idx_takeoff_runs_project_id on public.takeoff_runs(project_id);
create index if not exists idx_chat_logs_project_id on public.chat_logs(project_id);
create index if not exists idx_schedules_project_id on public.schedules(project_id);
