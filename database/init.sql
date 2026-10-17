create extension if not exists pgcrypto;

create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    email text unique not null,
    created_at timestamptz not null default now()
);

create table if not exists workspaces (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id) on delete cascade,
    company_name text not null,
    company_description text not null,
    product_name text not null,
    product_description text not null,
    email text not null,
    created_at timestamptz not null default now()
);

create table if not exists workspace_memories (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references workspaces(id) on delete cascade,
    fact text not null,
    category text not null default 'business',
    approved boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists searches (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id) on delete cascade,
    product_name text not null,
    product_description text not null,
    icp_definition jsonb not null default '{}'::jsonb,
    target_industries jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists product_documents (
    id uuid primary key default gen_random_uuid(),
    search_id uuid not null references searches(id) on delete cascade,
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists companies (
    id uuid primary key default gen_random_uuid(),
    search_id uuid not null references searches(id) on delete cascade,
    name text not null,
    domain text,
    industry text,
    description text,
    website text,
    match_score integer check (match_score between 0 and 100),
    why_recommended text,
    pain_points jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists company_documents (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists company_evidence (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    source_url text not null,
    evidence_text text not null,
    verified boolean not null default false,
    collected_at timestamptz not null default now()
);

create table if not exists leads (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    search_id uuid not null references searches(id) on delete cascade,
    status text not null default 'New',
    contact_name text,
    contact_email text,
    created_at timestamptz not null default now()
);

-- Raw activity used by lead intelligence (emails, calls, meetings, CRM notes).
create table if not exists lead_events (
    id uuid primary key default gen_random_uuid(),
    lead_id uuid not null references leads(id) on delete cascade,
    event_type text not null,
    content text not null,
    source text not null default 'manual',
    metadata jsonb not null default '{}'::jsonb,
    occurred_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);

-- Audit trail for changes to the lead pipeline stage.
create table if not exists lead_stage_history (
    id uuid primary key default gen_random_uuid(),
    lead_id uuid not null references leads(id) on delete cascade,
    old_stage text,
    new_stage text not null,
    reason text,
    confidence integer check (confidence between 0 and 100),
    created_at timestamptz not null default now()
);

-- Recommended work items shown in the workspace's daily task list.
-- workspace_id is kept as a UUID here; it can be linked with a foreign key
-- once the workspaces table is included in the shared schema.
create table if not exists tasks (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    lead_id uuid references leads(id) on delete cascade,
    title text not null,
    description text,
    status text not null default 'open',
    priority text not null default 'medium',
    due_at timestamptz,
    source text not null default 'ai',
    created_at timestamptz not null default now(),
    completed_at timestamptz
);

create index if not exists lead_events_lead_occurred_idx
    on lead_events (lead_id, occurred_at desc);

create index if not exists lead_stage_history_lead_created_idx
    on lead_stage_history (lead_id, created_at desc);

create index if not exists tasks_workspace_status_due_idx
    on tasks (workspace_id, status, due_at);

create table if not exists email_drafts (
    id uuid primary key default gen_random_uuid(),
    lead_id uuid unique not null references leads(id) on delete cascade,
    subject text not null,
    body text not null,
    status text not null default 'Draft',
    created_at timestamptz not null default now()
);

create table if not exists analytics (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id) on delete cascade,
    event_type text not null,
    event_details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

-- OAuth refresh tokens for user-authorized Google integrations.
create table if not exists google_connections (
    user_id uuid primary key references users(id) on delete cascade,
    email text,
    token_json text not null,
    updated_at timestamptz not null default now()
);
