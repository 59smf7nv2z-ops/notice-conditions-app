create table if not exists extract_hits (
  id bigserial primary key,
  ip text not null,
  created_at timestamptz not null default now()
);

create index if not exists extract_hits_ip_created on extract_hits (ip, created_at);
create index if not exists extract_hits_created on extract_hits (created_at);

create table if not exists extract_inflight (
  id text primary key,
  ip text not null,
  expires_at timestamptz not null
);

create index if not exists extract_inflight_ip on extract_inflight (ip);
create index if not exists extract_inflight_expires on extract_inflight (expires_at);
