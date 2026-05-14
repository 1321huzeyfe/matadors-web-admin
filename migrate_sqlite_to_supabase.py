# -*- coding: utf-8 -*-
"""Safely migrate MDFitness SQLite customers/products/sales into Supabase.

This script only reads the local SQLite database. It does not modify or delete
the original SQLite file.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SQLITE_DB_PATH = Path(
    r"C:\Users\huzeyfe\AppData\Local\MatadorsApp\MatadorsApp_Data\local\mdfitness\db\sales.db"
)
DATA_ROOT = SQLITE_DB_PATH.parents[3]
LOG_DIR = DATA_ROOT / "logs"
TABLES = ("customers", "products", "sales", "sale_items")
BATCH_SIZE = 100
_SUPABASE = None


def cashier_branch_id(conn: sqlite3.Connection, cashier_id: Any) -> str:
    if cashier_id in (None, "", 0, "0"):
        return ""
    try:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (cashier_id,)).fetchone()
        if row and row["username"]:
            return str(row["username"]).strip().lower().replace(" ", "_")
    except Exception:
        pass
    return f"cashier_{cashier_id}"


def setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"supabase_migration_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


def open_sqlite_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite DB bulunamadı: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    columns = [row["name"] for row in rows]
    if not columns:
        raise RuntimeError(f"SQLite tablo bulunamadı veya kolon okunamadı: {table}")
    return columns


def normalize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def read_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    columns = sqlite_columns(conn, table)
    col_sql = ", ".join(quote_identifier(column) for column in columns)
    rows = conn.execute(f"SELECT {col_sql} FROM {quote_identifier(table)} ORDER BY id").fetchall()
    rows = [
        {column: normalize_value(row[column]) for column in columns}
        for row in rows
    ]
    if table in ("customers", "products", "sales"):
        for row in rows:
            cashier_id = row.get("cashier_id")
            branch_id = cashier_branch_id(conn, cashier_id)
            if not cashier_id or not branch_id:
                raise RuntimeError(f"{table} id={row.get('id')} kasa kimligi olmadan aktarilamaz.")
            row["branch_id"] = branch_id
            row["profile_id"] = branch_id
            row["kasa_id"] = branch_id
            row["cashier_id"] = cashier_id
    return rows


def get_supabase_client():
    global _SUPABASE
    if _SUPABASE is not None:
        return _SUPABASE
    try:
        from services.supabase_client import supabase
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Supabase Python paketi bu ortamda kurulu değil. Aktarım için önce şu komutu çalıştırın: "
            "py -3 -m pip install supabase"
        ) from exc
    _SUPABASE = supabase
    return _SUPABASE


def supabase_columns_for_sqlite_columns(table: str, sqlite_columns_list: list[str]) -> list[str]:
    """Probe Supabase and keep only columns that really exist on the target table."""
    client = get_supabase_client()
    allowed: list[str] = []
    skipped: list[str] = []

    for column in sqlite_columns_list:
        try:
            client.table(table).select(column).limit(1).execute()
            allowed.append(column)
        except Exception as exc:
            skipped.append(column)
            logging.warning(
                "%s | Supabase kolon yok/erişilemiyor, payload'dan çıkarıldı: %s | %s",
                table,
                column,
                exc,
            )

    if not allowed:
        raise RuntimeError(f"{table} için Supabase'te kullanılabilir kolon bulunamadı.")
    if "id" not in allowed:
        raise RuntimeError(
            f"{table} için Supabase'te id kolonu bulunamadı; duplicate oluşturmadan upsert yapılamaz."
        )
    logging.info("%s | Supabase'e gönderilecek kolonlar: %s", table, ", ".join(allowed))
    if skipped:
        logging.info("%s | Atlanan SQLite kolonları: %s", table, ", ".join(skipped))
    return allowed


def filter_rows_to_columns(rows: list[dict[str, Any]], allowed_columns: list[str]) -> list[dict[str, Any]]:
    allowed = set(allowed_columns)
    return [
        {key: value for key, value in row.items() if key in allowed}
        for row in rows
    ]


def chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index:index + size] for index in range(0, len(rows), size)]


def upsert_batch(table: str, rows: list[dict[str, Any]], dry_run: bool = False) -> int:
    if not rows:
        return 0
    if dry_run:
        logging.info("DRY RUN | %s | %s kayıt Supabase'e gönderilmeyecek.", table, len(rows))
        return len(rows)

    # SQLite schema contains id on migrated tables. Using it as conflict key
    # keeps reruns idempotent when Supabase has the same primary key/unique index.
    supabase = get_supabase_client()
    supabase.table(table).upsert(rows, on_conflict="id").execute()
    return len(rows)


def migrate_table(conn: sqlite3.Connection, table: str, dry_run: bool = False) -> int:
    rows = read_rows(conn, table)
    logging.info("%s | SQLite kaynak kayıt: %s", table, len(rows))
    if not dry_run:
        sqlite_cols = list(rows[0].keys()) if rows else sqlite_columns(conn, table)
        allowed_cols = supabase_columns_for_sqlite_columns(table, sqlite_cols)
        rows = filter_rows_to_columns(rows, allowed_cols)
    migrated = 0

    for batch_no, batch in enumerate(chunks(rows, BATCH_SIZE), start=1):
        try:
            migrated += upsert_batch(table, batch, dry_run=dry_run)
            logging.info("%s | batch %s aktarıldı: %s kayıt", table, batch_no, len(batch))
        except Exception as batch_exc:
            logging.error("%s | batch %s hata: %s", table, batch_no, batch_exc)
            for row in batch:
                row_id = row.get("id", "?")
                try:
                    migrated += upsert_batch(table, [row], dry_run=dry_run)
                    logging.info("%s | satır aktarıldı | id=%s", table, row_id)
                except Exception as row_exc:
                    logging.exception(
                        "%s | satır aktarılamadı | id=%s | row=%s | hata=%s",
                        table,
                        row_id,
                        json.dumps(row, ensure_ascii=False, default=str),
                        row_exc,
                    )

    return migrated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MDFitness SQLite customers/products/sales/sale_items verilerini Supabase'e aktarır."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="SQLite verisini okur ve sayar; Supabase'e insert/upsert yapmaz.",
    )
    args = parser.parse_args()

    log_path = setup_logging()
    logging.info("Migration başladı. SQLite: %s", SQLITE_DB_PATH)
    logging.info("Log dosyası: %s", log_path)

    totals: dict[str, int] = {}
    try:
        with open_sqlite_readonly(SQLITE_DB_PATH) as conn:
            for table in TABLES:
                totals[table] = migrate_table(conn, table, dry_run=args.dry_run)
    except Exception as exc:
        logging.exception("Migration durdu: %s", exc)
        return 1

    print("")
    print("Aktarım tamamlandı." if not args.dry_run else "Dry-run tamamlandı.")
    print(f"Müşteri aktarılan: {totals.get('customers', 0)}")
    print(f"Ürün aktarılan: {totals.get('products', 0)}")
    print(f"Satış aktarılan: {totals.get('sales', 0)}")
    print(f"Satış kalemi aktarılan: {totals.get('sale_items', 0)}")
    print(f"Log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
