-- Safe Supabase sequence alignment for MatadorsApp migrations.
-- Use when inserts without an explicit id fail because the table sequence is behind existing rows.
-- No data rows are inserted, updated, deleted, dropped, or truncated.

select setval(
    pg_get_serial_sequence('public.customers', 'id'),
    greatest(coalesce((select max(id) from public.customers), 0) + 1, 1),
    false
);

select setval(
    pg_get_serial_sequence('public.products', 'id'),
    greatest(coalesce((select max(id) from public.products), 0) + 1, 1),
    false
);

select setval(
    pg_get_serial_sequence('public.sales', 'id'),
    greatest(coalesce((select max(id) from public.sales), 0) + 1, 1),
    false
);
