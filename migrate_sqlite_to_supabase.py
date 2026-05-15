# -*- coding: utf-8 -*-
"""Safely migrate local kasa SQLite sales.db files into Supabase.

Default mode is dry-run. The script scans:

    MatadorsApp_Data/local/*/db/sales.db

It never treats the manager DB as a business kasa source. Branch identity is
derived from the stable local profile folder name, not from customer/product
names or fuzzy matching.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from path_utils import get_data_dir, sanitize_kasa_name


TABLES = ("customers", "products", "sales")
BUSINESS_TABLES = {"customers", "products", "sales"}
REMOTE_KEY_ENTITIES = {
    "customers": "customer",
    "products": "product",
    "sales": "sale",
}
REMOTE_CONFLICT_COLUMNS = ("remote_unique_key", "source_key")
BATCH_SIZE = 100
SYSTEM_PROFILE_NAMES = {"manager", "admin", "shared", "genel-kasa", "genel_kasa"}
_SUPABASE = None


@dataclass(frozen=True)
class KasaSource:
    profile_name: str
    branch_id: str
    db_path: Path

    @property
    def stable_key(self) -> str:
        return f"branch_id:{self.branch_id}"


@dataclass
class SourcePlan:
    source: KasaSource
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def count(self, table: str) -> int:
        return len(self.rows.get(table, []))


def setup_logging(data_root: Path) -> Path:
    log_dir = data_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"supabase_migration_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )
    return log_path


def open_sqlite_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row["name"]) for row in rows}


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    return [row["name"] for row in rows]


def normalize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def is_missing(value: Any) -> bool:
    return value in (None, "", 0, "0")


def build_remote_unique_key(source: KasaSource, table: str, local_id: Any) -> str:
    entity = REMOTE_KEY_ENTITIES[table]
    return f"branch_id:{source.branch_id}:{entity}:{local_id}"


def discover_kasa_sources(data_root: Path) -> list[KasaSource]:
    local_root = data_root / "local"
    if not local_root.exists():
        return []

    sources: list[KasaSource] = []
    for db_path in sorted(local_root.glob("*/db/sales.db"), key=lambda item: str(item).casefold()):
        profile_name = db_path.parent.parent.name
        branch_id = sanitize_kasa_name(profile_name)
        if branch_id in SYSTEM_PROFILE_NAMES:
            logging.info("Skipped system profile: %s | db=%s", profile_name, db_path)
            continue
        sources.append(KasaSource(profile_name=profile_name, branch_id=branch_id, db_path=db_path))
    return sources


def exact_profile_cashier_id(conn: sqlite3.Connection, source: KasaSource) -> Any:
    if "users" not in sqlite_tables(conn):
        return None
    columns = sqlite_columns(conn, "users")
    if "id" not in columns or "username" not in columns:
        return None

    user_type_expr = "user_type" if "user_type" in columns else "''"
    rows = conn.execute(
        f"SELECT id, username, {user_type_expr} AS user_type FROM users ORDER BY id"
    ).fetchall()
    for row in rows:
        username = str(row["username"] or "")
        user_type = str(row["user_type"] or "").strip().lower()
        if user_type == "admin":
            continue
        if sanitize_kasa_name(username) == source.branch_id:
            return row["id"]
    return None


def enrich_business_row(
    conn: sqlite3.Connection,
    source: KasaSource,
    table: str,
    row: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    enriched = dict(row)
    local_id = enriched.get("id")
    if is_missing(local_id):
        warnings.append(f"{table} row has no local id; remote_unique_key cannot be generated safely")
    else:
        remote_key = build_remote_unique_key(source, table, local_id)
        enriched["local_id"] = local_id
        enriched["remote_unique_key"] = remote_key
        enriched["source_key"] = remote_key

    cashier_id = enriched.get("cashier_id")
    if is_missing(cashier_id):
        cashier_id = exact_profile_cashier_id(conn, source)
        if not is_missing(cashier_id):
            enriched["cashier_id"] = cashier_id
        else:
            warnings.append(f"{table} id={enriched.get('id')} has no cashier_id; branch still set from profile")

    # Stable branch identity comes from the local profile folder only.
    enriched["branch_id"] = source.branch_id
    enriched["profile_id"] = source.branch_id
    enriched["kasa_id"] = source.branch_id
    enriched["stable_branch_key"] = source.stable_key
    return enriched


def read_rows(conn: sqlite3.Connection, source: KasaSource, table: str, warnings: list[str]) -> list[dict[str, Any]]:
    columns = sqlite_columns(conn, table)
    if not columns:
        return []
    col_sql = ", ".join(quote_identifier(column) for column in columns)
    order_sql = " ORDER BY id" if "id" in columns else ""
    sqlite_rows = conn.execute(f"SELECT {col_sql} FROM {quote_identifier(table)}{order_sql}").fetchall()
    rows = [
        {column: normalize_value(sqlite_row[column]) for column in columns}
        for sqlite_row in sqlite_rows
    ]
    if table in BUSINESS_TABLES:
        return [enrich_business_row(conn, source, table, row, warnings) for row in rows]
    return rows


def build_plan(sources: list[KasaSource]) -> list[SourcePlan]:
    plans: list[SourcePlan] = []
    for source in sources:
        plan = SourcePlan(source=source)
        with open_sqlite_readonly(source.db_path) as conn:
            tables = sqlite_tables(conn)
            for table in TABLES:
                if table not in tables:
                    plan.rows[table] = []
                    plan.warnings.append(f"{table} table missing")
                    continue
                plan.rows[table] = read_rows(conn, source, table, plan.warnings)
        plans.append(plan)
    return plans


def get_supabase_client():
    global _SUPABASE
    if _SUPABASE is not None:
        return _SUPABASE
    try:
        from services.supabase_client import supabase
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Supabase Python package is not installed. Install it before --apply."
        ) from exc
    _SUPABASE = supabase
    return _SUPABASE


def supabase_columns_for_rows(table: str, rows: list[dict[str, Any]]) -> list[str]:
    if rows:
        candidates = [
            key
            for key in rows[0].keys()
            if not (table in BUSINESS_TABLES and key == "id")
        ]
    else:
        return []

    client = get_supabase_client()
    allowed: list[str] = []
    skipped: list[str] = []
    for column in candidates:
        try:
            client.table(table).select(column).limit(1).execute()
            allowed.append(column)
        except Exception as exc:
            skipped.append(column)
            logging.warning("%s | Supabase column skipped: %s | %s", table, column, exc)

    if not allowed:
        raise RuntimeError(f"{table} has no usable columns in Supabase; upsert refused.")
    if skipped:
        logging.info("%s | skipped columns: %s", table, ", ".join(skipped))
    return allowed


def filter_rows_to_columns(rows: list[dict[str, Any]], allowed_columns: list[str]) -> list[dict[str, Any]]:
    allowed = set(allowed_columns)
    return [{key: value for key, value in row.items() if key in allowed} for row in rows]


def payload_for_remote(table: str, row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    if table in BUSINESS_TABLES:
        # SQLite local id must not be sent as Supabase primary id. It lives in
        # local_id; remote_unique_key/source_key is the upsert identity.
        if "id" in payload and "local_id" not in payload:
            payload["local_id"] = payload["id"]
        payload.pop("id", None)
    return payload


def assert_no_remote_primary_id(table: str, rows: list[dict[str, Any]]) -> None:
    if table not in BUSINESS_TABLES:
        return
    leaking = [row.get("remote_unique_key") or row.get("source_key") or row.get("local_id") for row in rows if "id" in row]
    if leaking:
        raise RuntimeError(
            f"{table} apply refused; remote payload still contains Supabase primary key id. "
            f"Examples: {', '.join(str(item) for item in leaking[:5])}"
        )


def explain_apply_error(table: str, exc: Exception, rows: list[dict[str, Any]]) -> RuntimeError:
    text = str(exc)
    if "duplicate key value violates unique constraint" in text and f"{table}_pkey" in text:
        assert_no_remote_primary_id(table, rows)
        return RuntimeError(
            f"{table} apply failed although remote payload does not contain id. "
            "Supabase id sequence is likely behind existing rows, so Postgres generated an already-used primary key. "
            "Run the sequence alignment SQL before retrying apply."
        )
    return RuntimeError(f"{table} apply failed: {exc}")


def chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index:index + size] for index in range(0, len(rows), size)]


def collect_remote_key_issues(plans: list[SourcePlan]) -> dict[str, list[str]]:
    issues: dict[str, list[str]] = {}
    for table in TABLES:
        seen: dict[str, set[str]] = {}
        for plan in plans:
            for row in plan.rows.get(table, []):
                remote_key = str(row.get("remote_unique_key") or "")
                local_id = row.get("local_id")
                if not remote_key:
                    issues.setdefault(table, []).append(
                        f"{plan.source.branch_id}: local_id={local_id} has no remote_unique_key"
                    )
                    continue
                seen.setdefault(remote_key, set()).add(plan.source.branch_id)
        cross_branch_duplicates = [
            f"{remote_key} branches={sorted(branches)}"
            for remote_key, branches in seen.items()
            if len(branches) > 1
        ]
        if cross_branch_duplicates:
            issues.setdefault(table, []).extend(cross_branch_duplicates)
    return issues


def choose_conflict_column(table: str, allowed_columns: list[str]) -> str:
    allowed = set(allowed_columns)
    missing_required = [
        column
        for column in ("local_id", "branch_id", "profile_id", "kasa_id")
        if column not in allowed
    ]
    if missing_required:
        raise RuntimeError(
            f"{table} apply refused; Supabase table is missing required columns: "
            + ", ".join(missing_required)
        )
    for column in REMOTE_CONFLICT_COLUMNS:
        if column in allowed:
            return column
    raise RuntimeError(
        f"{table} apply refused; Supabase table needs remote_unique_key or source_key with a unique constraint."
    )


def print_report(plans: list[SourcePlan], log_path: Path, dry_run: bool) -> None:
    totals = {table: 0 for table in TABLES}
    print("")
    print("Kasa bazli migration plani")
    print("--------------------------")
    for plan in plans:
        source = plan.source
        for table in TABLES:
            totals[table] += plan.count(table)
        print(
            f"{source.branch_id}: "
            f"customers={plan.count('customers')} "
            f"products={plan.count('products')} "
            f"sales={plan.count('sales')} "
            f"| stable_key={source.stable_key} "
            f"| db={source.db_path}"
        )
        for warning in sorted(set(plan.warnings)):
            print(f"  warning: {warning}")
        for table in TABLES:
            sample = next((row for row in plan.rows.get(table, []) if row.get("remote_unique_key")), None)
            if sample:
                entity = REMOTE_KEY_ENTITIES[table]
                print(
                    f"  example: {entity} {sample.get('local_id')} -> "
                    f"{sample.get('remote_unique_key')}"
                )

    print("--------------------------")
    print(
        f"TOTAL: customers={totals['customers']} "
        f"products={totals['products']} "
        f"sales={totals['sales']}"
    )
    print("Mode: DRY RUN - Supabase write skipped." if dry_run else "Mode: APPLY")
    print(f"Log: {log_path}")


def apply_plan(plans: list[SourcePlan]) -> dict[str, int]:
    issues = collect_remote_key_issues(plans)
    if issues:
        raise RuntimeError(
            "Remote key issues detected. Apply refused: "
            + json.dumps(issues, ensure_ascii=False, default=str)
        )

    totals = {table: 0 for table in TABLES}
    for table in TABLES:
        all_rows: list[dict[str, Any]] = []
        for plan in plans:
            all_rows.extend(payload_for_remote(table, row) for row in plan.rows.get(table, []))
        if not all_rows:
            continue
        assert_no_remote_primary_id(table, all_rows)
        allowed_columns = supabase_columns_for_rows(table, all_rows)
        conflict_column = choose_conflict_column(table, allowed_columns)
        rows = filter_rows_to_columns(all_rows, allowed_columns)
        rows = [payload_for_remote(table, row) for row in rows]
        assert_no_remote_primary_id(table, rows)
        if rows:
            logging.info("%s | remote payload columns: %s", table, ", ".join(rows[0].keys()))
        for batch in chunks(rows, BATCH_SIZE):
            try:
                get_supabase_client().table(table).upsert(batch, on_conflict=conflict_column).execute()
            except Exception as exc:
                raise explain_apply_error(table, exc, batch) from exc
            totals[table] += len(batch)
            logging.info("%s | applied batch | conflict=%s | rows=%s", table, conflict_column, len(batch))
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan all local kasa sales.db files and prepare Supabase migration payloads."
    )
    parser.add_argument(
        "--data-root",
        default="",
        help="MatadorsApp_Data root. Defaults to the runtime data root.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and report only. This is the default unless --apply is used.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the exact scanned rows to Supabase. Refuses cross-kasa local id collisions.",
    )
    args = parser.parse_args()

    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run cannot be used together.")

    data_root = Path(args.data_root).expanduser().resolve() if args.data_root else Path(get_data_dir()).resolve()
    dry_run = not args.apply
    log_path = setup_logging(data_root)

    logging.info("Migration scan started. data_root=%s", data_root)
    sources = discover_kasa_sources(data_root)
    if not sources:
        logging.error("No kasa sales.db files found under %s", data_root / "local")
        return 1

    for source in sources:
        logging.info(
            "source | profile=%s | branch_id=%s | stable_key=%s | db=%s",
            source.profile_name,
            source.branch_id,
            source.stable_key,
            source.db_path,
        )

    try:
        plans = build_plan(sources)
        print_report(plans, log_path, dry_run=dry_run)
        issues = collect_remote_key_issues(plans)
        if issues:
            logging.warning("Remote key issues detected: %s", json.dumps(issues, ensure_ascii=False, default=str))
            print("Remote key warning: some rows are missing a safe remote key.")
        if not dry_run:
            totals = apply_plan(plans)
            print("")
            print(
                "Apply completed: "
                f"customers={totals['customers']} "
                f"products={totals['products']} "
                f"sales={totals['sales']}"
            )
    except Exception as exc:
        logging.exception("Migration stopped: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
