-- Safe Supabase migration for MatadorsApp branch/cashier isolation.
-- Adds nullable columns only. Existing rows are not guessed or reassigned.

alter table if exists public.customers add column if not exists local_id bigint;
alter table if exists public.customers add column if not exists branch_id text;
alter table if exists public.customers add column if not exists profile_id text;
alter table if exists public.customers add column if not exists kasa_id text;
alter table if exists public.customers add column if not exists remote_unique_key text;
alter table if exists public.customers add column if not exists source_key text;
alter table if exists public.customers add column if not exists cashier_id text;

alter table if exists public.products add column if not exists local_id bigint;
alter table if exists public.products add column if not exists branch_id text;
alter table if exists public.products add column if not exists profile_id text;
alter table if exists public.products add column if not exists kasa_id text;
alter table if exists public.products add column if not exists remote_unique_key text;
alter table if exists public.products add column if not exists source_key text;
alter table if exists public.products add column if not exists cashier_id text;

alter table if exists public.sales add column if not exists local_id bigint;
alter table if exists public.sales add column if not exists branch_id text;
alter table if exists public.sales add column if not exists profile_id text;
alter table if exists public.sales add column if not exists kasa_id text;
alter table if exists public.sales add column if not exists remote_unique_key text;
alter table if exists public.sales add column if not exists source_key text;
alter table if exists public.sales add column if not exists cashier_id text;

create index if not exists idx_customers_branch_identity on public.customers (branch_id, kasa_id, profile_id, cashier_id);
create index if not exists idx_products_branch_identity on public.products (branch_id, kasa_id, profile_id, cashier_id);
create index if not exists idx_sales_branch_identity on public.sales (branch_id, kasa_id, profile_id, cashier_id);

create unique index if not exists idx_customers_remote_unique_key on public.customers (remote_unique_key);
create unique index if not exists idx_products_remote_unique_key on public.products (remote_unique_key);
create unique index if not exists idx_sales_remote_unique_key on public.sales (remote_unique_key);

create index if not exists idx_customers_source_key on public.customers (source_key);
create index if not exists idx_products_source_key on public.products (source_key);
create index if not exists idx_sales_source_key on public.sales (source_key);
