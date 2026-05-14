# -*- coding: utf-8 -*-
"""Optional Supabase sync layer for MatadorsApp.

SQLite remains the source of truth. Every public sync method catches Supabase
errors, writes a local queue/log entry, and returns without blocking the app.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from path_utils import get_auth_db_path, get_data_dir, get_db_path, get_kasa_db_path, sanitize_kasa_name
from performance import measure, perf_timer


SYNC_TABLES = ("users", "customers", "products", "sales", "sale_items")
TABLE_ALIASES = {
    "users": ("users", "kullanicilar", "kullanıcılar"),
}
DEFAULT_SQLITE_DB_PATH = Path(get_kasa_db_path("mdfitness"))
MANAGER_SQLITE_DB_PATH = Path(get_db_path())
QUEUE_FILE = Path(get_data_dir()) / "local" / "mdfitness" / "db" / "supabase_sync_queue.jsonl"
LOG_FILE = Path(get_data_dir()) / "logs" / "supabase_sync.log"
DEVICE_CONFIG_FILE = Path(get_data_dir()) / "config.json"
BATCH_SIZE = 100
BRANCH_COLUMNS = ("branch_id", "profile_id", "kasa_id", "cashier_id")
BUSINESS_TABLES_REQUIRING_BRANCH = ("customers", "products", "sales")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _setup_logger() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("matadors_supabase_sync")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(file_handler)
    return logger


LOGGER = _setup_logger()


def _json_default(value: Any) -> str:
    return str(value)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_device_id() -> str:
    """Return a stable local device id without touching business data."""
    DEVICE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config = _read_json_file(DEVICE_CONFIG_FILE)
    device_id = str(config.get("device_id") or "").strip()
    if device_id:
        return device_id
    device_id = str(uuid.uuid4())
    config["device_id"] = device_id
    try:
        DEVICE_CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        LOGGER.warning("device_id config yazilamadi | hata=%s", exc)
    return device_id


def branch_id_from_user(user: dict[str, Any] | None) -> str:
    if not user:
        return ""
    username = str(user.get("username") or "").strip()
    if not username:
        return ""
    return sanitize_kasa_name(username)


class JsonSyncQueue:
    """Small JSONL queue for failed Supabase sync attempts."""

    def __init__(self, path: str | Path = QUEUE_FILE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def enqueue(
        self,
        operation: str,
        table: str,
        payload: dict[str, Any],
        retry_count: int = 0,
        error: str = "",
    ) -> str:
        item_id = str(uuid.uuid4())
        item = {
            "id": item_id,
            "operation": operation,
            "table": table,
            "payload": payload,
            "created_at": _now(),
            "retry_count": int(retry_count or 0),
            "last_error": error,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, default=_json_default) + "\n")
        return item_id

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError as exc:
                    LOGGER.error("queue | bozuk satır | line=%s | hata=%s", line_no, exc)
                    continue
                if isinstance(item, dict):
                    items.append(item)
        return items

    def rewrite(self, items: list[dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False, default=_json_default) + "\n")
        tmp.replace(self.path)


class SupabaseSync:
    """Best-effort Supabase sync. Never let network errors block SQLite flow."""

    def __init__(self, queue: JsonSyncQueue | None = None, dry_run: bool = False):
        self.queue = queue or JsonSyncQueue()
        self.dry_run = dry_run
        self._client = None
        self._column_cache: dict[str, set[str]] = {}
        self._table_cache: dict[str, str] = {}

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from services.supabase_client import supabase
        except Exception as exc:
            raise RuntimeError(
                "Supabase bağlantısı yüklenemedi. Yerel SQLite işlemine devam edilebilir."
            ) from exc
        self._client = supabase
        return self._client

    def _candidate_tables(self, table: str) -> tuple[str, ...]:
        return TABLE_ALIASES.get(table, (table,))

    def _resolve_table(self, table: str) -> str:
        if table in self._table_cache:
            return self._table_cache[table]
        client = self._get_client()
        last_error: Exception | None = None
        for candidate in self._candidate_tables(table):
            try:
                client.table(candidate).select("id").limit(1).execute()
                self._table_cache[table] = candidate
                if candidate != table:
                    LOGGER.info("%s | Supabase tablo alias kullaniliyor: %s", table, candidate)
                return candidate
            except Exception as exc:
                last_error = exc
                LOGGER.warning("%s | Supabase tablo denenemedi | candidate=%s | hata=%s", table, candidate, exc)
        raise RuntimeError(f"{table} Supabase tablosu bulunamadi/erisilemedi: {last_error}")

    def _table_columns(self, table: str, candidate_columns: list[str]) -> set[str]:
        if table in self._column_cache:
            return self._column_cache[table]
        client = self._get_client()
        actual_table = self._resolve_table(table)
        allowed: set[str] = set()
        skipped: list[str] = []
        for column in candidate_columns:
            try:
                client.table(actual_table).select(column).limit(1).execute()
                allowed.add(column)
            except Exception as exc:
                skipped.append(column)
                LOGGER.warning("%s | kolon atlandı | column=%s | hata=%s", table, column, exc)
        if "id" not in allowed:
            raise RuntimeError(f"{table} tablosunda id kolonu doğrulanamadı; upsert yapılmadı.")
        self._column_cache[table] = allowed
        LOGGER.info("%s | aktif Supabase kolonları: %s", table, ", ".join(sorted(allowed)))
        if skipped:
            LOGGER.info("%s | Supabase'te olmayan/erişilemeyen kolonlar: %s", table, ", ".join(skipped))
        return allowed

    def _filter_payload(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = self._table_columns(table, list(payload.keys()))
        return {key: value for key, value in payload.items() if key in allowed}

    def _upsert_payload(self, table: str, payload: dict[str, Any]) -> bool:
        if self.dry_run:
            LOGGER.info("DRY RUN | %s | row_id=%s", table, payload.get("id"))
            return True
        with perf_timer("supabase_sync_suresi", f"upsert table={table} row_id={payload.get('id')}"):
            filtered = self._filter_payload(table, payload)
            self._get_client().table(self._resolve_table(table)).upsert(filtered, on_conflict="id").execute()
        return True

    @measure("supabase_sync_suresi", lambda self, table, payload, operation="upsert": f"{operation} table={table} row_id={payload.get('id') if isinstance(payload, dict) else ''}")
    def upsert(self, table: str, payload: dict[str, Any], operation: str = "upsert") -> bool:
        if table not in SYNC_TABLES:
            LOGGER.error("Bilinmeyen Supabase sync tablosu: %s", table)
            return False
        try:
            ok = self._upsert_payload(table, payload)
            LOGGER.info("%s | %s başarılı | row_id=%s", table, operation, payload.get("id"))
            return ok
        except Exception as exc:
            try:
                queue_id = self.queue.enqueue(operation, table, payload, error=str(exc))
                LOGGER.error(
                    "%s | %s başarısız, kuyruğa alındı | row_id=%s | queue_id=%s | hata=%s",
                    table,
                    operation,
                    payload.get("id"),
                    queue_id,
                    exc,
                )
            except Exception as queue_exc:
                LOGGER.exception(
                    "%s | %s başarısız, kuyruk yazılamadı | row_id=%s | hata=%s | kuyruk_hata=%s",
                    table,
                    operation,
                    payload.get("id"),
                    exc,
                    queue_exc,
                )
            return False

    def upsert_customer(self, payload: dict[str, Any]) -> bool:
        return self.upsert("customers", payload)

    def upsert_user(self, payload: dict[str, Any]) -> bool:
        return self.upsert("users", payload)

    def upsert_product(self, payload: dict[str, Any]) -> bool:
        return self.upsert("products", payload)

    def upsert_sale(self, payload: dict[str, Any]) -> bool:
        return self.upsert("sales", payload)

    def upsert_sale_item(self, payload: dict[str, Any]) -> bool:
        return self.upsert("sale_items", payload)

    @measure("queue_isleme_suresi", lambda self, limit=100, dry_run=None: f"limit={limit} dry_run={dry_run}")
    def process_queue(self, limit: int = 100, dry_run: bool | None = None) -> dict[str, int]:
        previous_dry_run = self.dry_run
        if dry_run is not None:
            self.dry_run = dry_run
        items = self.queue.read_all()
        remaining: list[dict[str, Any]] = []
        processed = 0
        failed = 0
        kept = 0

        try:
            for item in items:
                if processed >= limit:
                    remaining.append(item)
                    kept += 1
                    continue
                table = str(item.get("table") or "")
                payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                row_id = payload.get("id")
                try:
                    payload = enrich_payload_for_supabase(DEFAULT_SQLITE_DB_PATH, table, payload)
                    self._upsert_payload(table, payload)
                    processed += 1
                    LOGGER.info("%s | kuyruk gönderildi | row_id=%s | queue_id=%s", table, row_id, item.get("id"))
                except Exception as exc:
                    item["retry_count"] = int(item.get("retry_count") or 0) + 1
                    item["last_error"] = str(exc)
                    remaining.append(item)
                    failed += 1
                    LOGGER.error(
                        "%s | kuyruk başarısız | row_id=%s | queue_id=%s | retry=%s | hata=%s",
                        table,
                        row_id,
                        item.get("id"),
                        item["retry_count"],
                        exc,
                    )
            self.queue.rewrite(remaining)
            return {"processed": processed, "failed": failed, "remaining": len(remaining), "kept": kept}
        finally:
            self.dry_run = previous_dry_run

    def _select_rows_for_branch(self, table: str, branch_id: str, cashier_id: int | None = None) -> list[dict[str, Any]]:
        """Read rows for one branch only; never falls back to unfiltered data."""
        client = self._get_client()
        actual_table = self._resolve_table(table)
        attempts: list[tuple[str, Any]] = []
        if branch_id:
            attempts.extend([("branch_id", branch_id), ("profile_id", branch_id), ("kasa_id", branch_id)])
        if cashier_id is not None:
            attempts.append(("cashier_id", cashier_id))
        for column, value in attempts:
            try:
                response = client.table(actual_table).select("*").eq(column, value).execute()
                rows = getattr(response, "data", None) or []
                LOGGER.info("%s | branch pull | column=%s | value=%s | rows=%s", table, column, value, len(rows))
                if rows:
                    return [dict(row) for row in rows if isinstance(row, dict)]
            except Exception as exc:
                LOGGER.warning("%s | branch pull filtre denenemedi | column=%s | hata=%s", table, column, exc)
        LOGGER.warning("%s | branch pull atlandi; Supabase'te uygun branch/cashier kolonu dogrulanamadi", table)
        return []

    def _select_users_for_scope(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        client = self._get_client()
        actual_table = self._resolve_table("users")
        try:
            if user.get("user_type") == "admin":
                response = client.table(actual_table).select("*").execute()
            else:
                response = client.table(actual_table).select("*").eq("username", user.get("username")).execute()
            rows = getattr(response, "data", None) or []
            LOGGER.info("users | bootstrap pull | scope=%s | rows=%s", user.get("username"), len(rows))
            return [dict(row) for row in rows if isinstance(row, dict)]
        except Exception as exc:
            LOGGER.warning("users | bootstrap pull atlandi | hata=%s", exc)
            return []

    @measure("supabase_sync_suresi", lambda self, db_path, user, include_sales=False: f"bootstrap user={user.get('username') if isinstance(user, dict) else ''} include_sales={include_sales}")
    def bootstrap_profile_from_supabase(
        self,
        db_path: str | Path,
        user: dict[str, Any],
        include_sales: bool = False,
    ) -> dict[str, int]:
        """Best-effort first-open pull. Filters every business row by branch/cashier."""
        branch_id = branch_id_from_user(user)
        cashier_id = None if user.get("user_type") == "admin" else int(user.get("id") or 0)
        totals = {"users": 0, "customers": 0, "products": 0, "sales": 0, "sale_items": 0}
        try:
            users = self._select_users_for_scope(user)
            totals["users"] = upsert_sqlite_rows(db_path, "users", users)
            if user.get("user_type") == "admin":
                LOGGER.info("bootstrap | admin scope: business pull skipped; cashier profiles pull their own branch on login")
                return totals
            if not branch_id and cashier_id is None:
                LOGGER.warning("bootstrap | branch_id/cashier_id yok; veri cekilmedi | user=%s", user)
                return totals
            for table in ("customers", "products"):
                rows = self._select_rows_for_branch(table, branch_id, cashier_id)
                totals[table] = upsert_sqlite_rows(db_path, table, rows)
            if include_sales:
                sales = self._select_rows_for_branch("sales", branch_id, cashier_id)
                totals["sales"] = upsert_sqlite_rows(db_path, "sales", sales)
                sale_ids = [row.get("id") for row in sales if row.get("id") is not None]
                totals["sale_items"] = pull_sale_items_for_sales(self._get_client(), db_path, sale_ids)
            LOGGER.info("bootstrap | tamam | branch_id=%s | cashier_id=%s | totals=%s", branch_id, cashier_id, totals)
        except Exception as exc:
            LOGGER.exception("bootstrap | hata | branch_id=%s | cashier_id=%s | hata=%s", branch_id, cashier_id, exc)
        return totals


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    columns = [row["name"] for row in rows]
    if not columns:
        raise RuntimeError(f"SQLite tablo bulunamadı veya kolon okunamadı: {table}")
    return columns


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone()
    return bool(row)


def _local_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()}


def _user_for_cashier_id(conn: sqlite3.Connection, cashier_id: Any) -> dict[str, Any] | None:
    if cashier_id in (None, "") or not _table_exists(conn, "users"):
        return None
    row = conn.execute("SELECT * FROM users WHERE id = ?", (cashier_id,)).fetchone()
    return dict(row) if row else None


def _branch_for_cashier_id(conn: sqlite3.Connection, cashier_id: Any) -> str:
    user = _user_for_cashier_id(conn, cashier_id)
    if user:
        return branch_id_from_user(user)
    if cashier_id not in (None, ""):
        return f"cashier_{cashier_id}"
    return ""


def _is_missing_cashier_id(value: Any) -> bool:
    text = str(value or "").strip()
    return text in ("", "0", "None", "none", "null")


def _auth_password_hash_for_user(db_path: str | Path, payload: dict[str, Any]) -> str:
    candidates = []
    try:
        candidates.append(Path(db_path).parent / "matadors_kasa_auth.db")
    except Exception:
        pass
    candidates.append(Path(get_auth_db_path()))
    seen = set()
    for auth_path in candidates:
        key = str(auth_path).casefold()
        if key in seen or not auth_path.exists():
            continue
        seen.add(key)
        try:
            with closing(sqlite3.connect(auth_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT password_hash FROM auth_users WHERE id = ? OR username = ? ORDER BY id LIMIT 1",
                    (payload.get("id"), payload.get("username")),
                ).fetchone()
                if row and row["password_hash"]:
                    return str(row["password_hash"])
        except Exception as exc:
            LOGGER.warning("users | auth password hash okunamadi | auth_db=%s | hata=%s", auth_path, exc)
    return ""


def enrich_payload_for_supabase(db_path: str | Path, table: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Add branch/profile/device metadata for Supabase if columns exist there."""
    enriched = dict(payload)
    try:
        if table == "users":
            branch_id = branch_id_from_user(enriched)
            if branch_id:
                enriched["branch_id"] = branch_id
                enriched["profile_id"] = branch_id
                enriched["kasa_id"] = branch_id
            if enriched.get("id") is not None:
                enriched["cashier_id"] = str(enriched.get("id"))
            if enriched.get("user_type") and not enriched.get("role"):
                enriched["role"] = enriched.get("user_type")
            enriched["archived"] = int(enriched.get("archived", 0) or 0)
            enriched["is_active"] = int(enriched.get("is_active", 1) if enriched.get("is_active") is not None else 1)
            password_hash = _auth_password_hash_for_user(db_path, enriched)
            if password_hash:
                enriched["password_hash"] = password_hash
                enriched["password"] = password_hash
            enriched["device_id"] = get_device_id()
            return enriched
        path = Path(db_path)
        uri = f"file:{path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            cashier_id = enriched.get("cashier_id")
            if table == "sale_items" and not cashier_id and enriched.get("sale_id") is not None and _table_exists(conn, "sales"):
                sale = conn.execute("SELECT cashier_id FROM sales WHERE id = ?", (enriched.get("sale_id"),)).fetchone()
                if sale and "cashier_id" in sale.keys():
                    cashier_id = sale["cashier_id"]
                    enriched["cashier_id"] = cashier_id
            branch_id = _branch_for_cashier_id(conn, cashier_id)
            if table in BUSINESS_TABLES_REQUIRING_BRANCH and _is_missing_cashier_id(cashier_id):
                raise RuntimeError(f"{table} satiri cashier_id olmadan Supabase'e gonderilemez.")
            if branch_id:
                enriched.setdefault("branch_id", branch_id)
                enriched.setdefault("profile_id", branch_id)
                enriched.setdefault("kasa_id", branch_id)
            if table in BUSINESS_TABLES_REQUIRING_BRANCH and not branch_id:
                raise RuntimeError(f"{table} satiri icin kalici kasa kimligi uretilemedi.")
            enriched.setdefault("device_id", get_device_id())
    except Exception as exc:
        LOGGER.warning("%s | Supabase metadata eklenemedi | row_id=%s | hata=%s", table, payload.get("id"), exc)
    return enriched


def upsert_sqlite_rows(db_path: str | Path, table: str, rows: list[dict[str, Any]]) -> int:
    """Upsert Supabase rows into SQLite using only existing local columns."""
    if not rows:
        return 0
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            columns = _local_table_columns(conn, table)
            if not columns or "id" not in columns:
                LOGGER.warning("%s | local tablo/ id yok, bootstrap yazimi atlandi", table)
                return 0
            for row in rows:
                if table == "users":
                    row = {
                        **row,
                        "user_type": row.get("user_type") or row.get("role"),
                        "full_name": row.get("full_name") or row.get("username") or "",
                        "email": row.get("email") or "",
                        "archived": row.get("archived", 0),
                        "is_active": row.get("is_active", 1),
                    }
                payload = {key: _normalize_value(value) for key, value in row.items() if key in columns}
                if "id" not in payload or payload.get("id") is None:
                    continue
                names = list(payload.keys())
                placeholders = ", ".join("?" for _ in names)
                col_sql = ", ".join(_quote_identifier(name) for name in names)
                update_sql = ", ".join(
                    f"{_quote_identifier(name)} = excluded.{_quote_identifier(name)}"
                    for name in names
                    if name != "id"
                )
                if update_sql:
                    sql = (
                        f"INSERT INTO {_quote_identifier(table)} ({col_sql}) VALUES ({placeholders}) "
                        f"ON CONFLICT(id) DO UPDATE SET {update_sql}"
                    )
                else:
                    sql = f"INSERT OR IGNORE INTO {_quote_identifier(table)} ({col_sql}) VALUES ({placeholders})"
                try:
                    conn.execute(sql, [payload[name] for name in names])
                    written += 1
                except Exception as exc:
                    LOGGER.error("%s | bootstrap row yazilamadi | row_id=%s | hata=%s", table, payload.get("id"), exc)
        if table == "users":
            upsert_auth_users_from_supabase(rows)
    except Exception as exc:
        LOGGER.exception("%s | bootstrap local yazim hata | db=%s | hata=%s", table, db_path, exc)
    return written


def upsert_auth_users_from_supabase(rows: list[dict[str, Any]]) -> int:
    written = 0
    auth_path = Path(get_auth_db_path())
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(auth_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    user_type TEXT NOT NULL CHECK(user_type IN ('admin', 'cashier')),
                    full_name TEXT NOT NULL,
                    email TEXT DEFAULT ''
                )
                """
            )
            for row in rows:
                username = str(row.get("username") or "").strip()
                password_hash = str(row.get("password_hash") or row.get("password") or "").strip()
                user_type = str(row.get("user_type") or row.get("role") or "cashier").strip()
                if user_type not in ("admin", "cashier"):
                    user_type = "cashier"
                if not username or not password_hash:
                    LOGGER.warning("users | auth bootstrap atlandi | username=%s | password_hash_yok=%s", username, not password_hash)
                    continue
                conn.execute(
                    """
                    INSERT INTO auth_users(id, username, password_hash, user_type, full_name, email)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                        password_hash = excluded.password_hash,
                        user_type = excluded.user_type,
                        full_name = excluded.full_name,
                        email = excluded.email
                    """,
                    (
                        row.get("id"),
                        username,
                        password_hash,
                        user_type,
                        row.get("full_name") or username,
                        row.get("email") or "",
                    ),
                )
                written += 1
    except Exception as exc:
        LOGGER.exception("users | auth bootstrap yazim hata | auth_db=%s | hata=%s", auth_path, exc)
    return written


def pull_sale_items_for_sales(client: Any, db_path: str | Path, sale_ids: list[Any]) -> int:
    if not sale_ids:
        return 0
    rows: list[dict[str, Any]] = []
    for sale_id in sale_ids:
        try:
            response = client.table("sale_items").select("*").eq("sale_id", sale_id).execute()
            data = getattr(response, "data", None) or []
            rows.extend(dict(item) for item in data if isinstance(item, dict))
        except Exception as exc:
            LOGGER.warning("sale_items | sale_id filtresi denenemedi | sale_id=%s | hata=%s", sale_id, exc)
    return upsert_sqlite_rows(db_path, "sale_items", rows)


def read_sqlite_table(db_path: str | Path, table: str) -> list[dict[str, Any]]:
    path = Path(db_path)
    uri = f"file:{path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        columns = sqlite_columns(conn, table)
        col_sql = ", ".join(_quote_identifier(column) for column in columns)
        rows = conn.execute(f"SELECT {col_sql} FROM {_quote_identifier(table)} ORDER BY id").fetchall()
        return [
            {column: _normalize_value(row[column]) for column in columns}
            for row in rows
        ]


def read_sqlite_row(db_path: str | Path, table: str, row_id: int) -> dict[str, Any] | None:
    path = Path(db_path)
    uri = f"file:{path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        columns = sqlite_columns(conn, table)
        col_sql = ", ".join(_quote_identifier(column) for column in columns)
        row = conn.execute(
            f"SELECT {col_sql} FROM {_quote_identifier(table)} WHERE id = ?",
            (row_id,),
        ).fetchone()
        if not row:
            return None
        return {column: _normalize_value(row[column]) for column in columns}


def read_sqlite_rows_where(db_path: str | Path, table: str, where_sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    path = Path(db_path)
    uri = f"file:{path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        columns = sqlite_columns(conn, table)
        col_sql = ", ".join(_quote_identifier(column) for column in columns)
        rows = conn.execute(
            f"SELECT {col_sql} FROM {_quote_identifier(table)} WHERE {where_sql} ORDER BY id",
            params,
        ).fetchall()
        return [
            {column: _normalize_value(row[column]) for column in columns}
            for row in rows
        ]


def read_local_users_for_supabase(
    db_path: str | Path = MANAGER_SQLITE_DB_PATH,
    auth_db_path: str | Path = Path(get_auth_db_path()),
) -> list[dict[str, Any]]:
    """Read local users joined with auth hashes; never exposes plain passwords."""
    users: dict[int, dict[str, Any]] = {}
    db_path = Path(db_path)
    auth_db_path = Path(auth_db_path)

    if db_path.exists():
        uri = f"file:{db_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            if _table_exists(conn, "users"):
                columns = _local_table_columns(conn, "users")
                wanted = [col for col in ("id", "username", "user_type", "full_name", "email", "archived", "is_active") if col in columns]
                col_sql = ", ".join(_quote_identifier(col) for col in wanted)
                for row in conn.execute(f"SELECT {col_sql} FROM users ORDER BY id"):
                    users[int(row["id"])] = {key: _normalize_value(row[key]) for key in row.keys()}

    if auth_db_path.exists():
        uri = f"file:{auth_db_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            if _table_exists(conn, "auth_users"):
                for row in conn.execute(
                    "SELECT id, username, password_hash, user_type, full_name, email, COALESCE(archived, 0) AS archived, COALESCE(is_active, 1) AS is_active FROM auth_users ORDER BY id"
                ):
                    user_id = int(row["id"])
                    payload = users.get(user_id, {})
                    payload.update({key: _normalize_value(row[key]) for key in row.keys()})
                    users[user_id] = payload

    return [users[key] for key in sorted(users)]


@measure("supabase_sync_suresi", lambda db_path, table, row_id: f"live_row table={table} row_id={row_id}")
def safe_upsert_row_from_sqlite(db_path: str | Path, table: str, row_id: int) -> bool:
    """Best-effort row sync helper for live SQLite hooks."""
    try:
        payload = read_sqlite_row(db_path, table, int(row_id))
        if not payload:
            LOGGER.warning("%s | SQLite satır bulunamadı, sync atlandı | row_id=%s", table, row_id)
            return False
        payload = enrich_payload_for_supabase(db_path, table, payload)
        return SupabaseSync().upsert(table, payload, operation="live_hook")
    except Exception as exc:
        LOGGER.exception("%s | live hook hata | row_id=%s | hata=%s", table, row_id, exc)
        return False


@measure("supabase_sync_suresi", lambda db_path, sale_id: f"sale_with_items sale_id={sale_id}")
def safe_upsert_sale_with_items(db_path: str | Path, sale_id: int) -> bool:
    """Best-effort sale + sale_items sync helper for live sale hooks."""
    ok = safe_upsert_row_from_sqlite(db_path, "sales", int(sale_id))
    try:
        items = read_sqlite_rows_where(db_path, "sale_items", "sale_id = ?", (int(sale_id),))
        sync = SupabaseSync()
        for item in items:
            item = enrich_payload_for_supabase(db_path, "sale_items", item)
            item_ok = sync.upsert_sale_item(item)
            ok = ok and item_ok
        LOGGER.info("sales | sale_items live hook tamamlandı | sale_id=%s | item_count=%s", sale_id, len(items))
    except Exception as exc:
        LOGGER.exception("sale_items | live hook hata | sale_id=%s | hata=%s", sale_id, exc)
        ok = False
    return ok


@measure("queue_isleme_suresi", lambda limit=100: f"process_queue_once_silent limit={limit}")
def process_queue_once_silent(limit: int = 100) -> dict[str, int]:
    """Process queued sync items once; intended for app startup."""
    try:
        result = SupabaseSync().process_queue(limit=limit)
        LOGGER.info("startup queue process | %s", result)
        return result
    except Exception as exc:
        LOGGER.exception("startup queue process hata: %s", exc)
        return {"processed": 0, "failed": 0, "remaining": 0, "kept": 0}


@measure("supabase_sync_suresi", lambda db_path, user, include_sales=False: f"bootstrap_profile_once_silent user={user.get('username') if isinstance(user, dict) else ''}")
def bootstrap_profile_once_silent(
    db_path: str | Path,
    user: dict[str, Any],
    include_sales: bool = False,
) -> dict[str, int]:
    """Pull only the current user's branch data from Supabase without blocking UI."""
    try:
        return SupabaseSync().bootstrap_profile_from_supabase(db_path, user, include_sales=include_sales)
    except Exception as exc:
        LOGGER.exception("bootstrap_profile_once_silent hata | user=%s | hata=%s", user, exc)
        return {"users": 0, "customers": 0, "products": 0, "sales": 0, "sale_items": 0}


def manual_sync_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE_DB_PATH,
    dry_run: bool = True,
    enqueue_on_failure: bool = True,
) -> dict[str, int]:
    """Manual sync helper for testing or scheduled jobs."""
    sync = SupabaseSync(dry_run=dry_run)
    totals: dict[str, int] = {}
    for table in SYNC_TABLES:
        rows = read_sqlite_table(db_path, table)
        totals[table] = len(rows)
        LOGGER.info("manual_sync | %s | kaynak kayıt=%s | dry_run=%s", table, len(rows), dry_run)
        if dry_run:
            continue
        for batch_no, batch_start in enumerate(range(0, len(rows), BATCH_SIZE), start=1):
            batch = rows[batch_start:batch_start + BATCH_SIZE]
            LOGGER.info("manual_sync | %s | batch=%s | kayıt=%s", table, batch_no, len(batch))
            for row in batch:
                row = enrich_payload_for_supabase(db_path, table, row)
                ok = sync.upsert(table, row, operation="manual_sync")
                if not ok and not enqueue_on_failure:
                    LOGGER.error("%s | manual sync satır hata | row_id=%s", table, row.get("id"))
    return totals


def manual_sync_users(
    db_path: str | Path = MANAGER_SQLITE_DB_PATH,
    dry_run: bool = True,
    enqueue_on_failure: bool = True,
) -> dict[str, int]:
    """Full upsert local users/auth_users into Supabase users by id."""
    rows = read_local_users_for_supabase(db_path)
    sync = SupabaseSync(dry_run=dry_run)
    result = {"users": len(rows), "synced": 0, "failed": 0}
    LOGGER.info("manual_users_sync | kaynak kayıt=%s | dry_run=%s", len(rows), dry_run)
    for row in rows:
        payload = enrich_payload_for_supabase(db_path, "users", row)
        if dry_run:
            LOGGER.info("DRY RUN | users | row_id=%s | payload_keys=%s", payload.get("id"), sorted(payload.keys()))
            continue
        ok = sync.upsert_user(payload)
        if ok:
            result["synced"] += 1
        else:
            result["failed"] += 1
            if not enqueue_on_failure:
                LOGGER.error("users | manual users sync satir hata | row_id=%s", payload.get("id"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="MatadorsApp Supabase sync altyapısı test aracı.")
    parser.add_argument("--db-path", default=str(DEFAULT_SQLITE_DB_PATH), help="SQLite DB yolu.")
    parser.add_argument("--dry-run", action="store_true", help="Sadece SQLite kayıt sayılarını yazdırır.")
    parser.add_argument("--sync", action="store_true", help="SQLite kayıtlarını Supabase'e göndermeyi dener.")
    parser.add_argument("--process-queue", action="store_true", help="Bekleyen JSON kuyruğu göndermeyi dener.")
    parser.add_argument("--limit", type=int, default=100, help="Kuyruk işleme limiti.")
    parser.add_argument("--sync-users", action="store_true", help="Manager users/auth_users kayitlarini Supabase users tablosuna full upsert eder.")
    args = parser.parse_args()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    if not any(isinstance(handler, logging.StreamHandler) for handler in LOGGER.handlers):
        LOGGER.addHandler(stream)

    if args.process_queue:
        result = SupabaseSync(dry_run=args.dry_run).process_queue(limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.sync_users:
        users_db_path = MANAGER_SQLITE_DB_PATH if args.db_path == str(DEFAULT_SQLITE_DB_PATH) else Path(args.db_path)
        result = manual_sync_users(users_db_path, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    dry_run = args.dry_run or not args.sync
    totals = manual_sync_from_sqlite(args.db_path, dry_run=dry_run)
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
