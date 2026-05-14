# -*- coding: utf-8 -*-
"""Shared master data ownership for products, customers and stock adjustments."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from profile_manager import ProfileManager
from safe_io import atomic_write_json
from path_utils import get_local_root


LOCK_TIMEOUT_SECONDS = 120
LOCK_MESSAGE = "Bu veri şu anda başka bir kullanıcı tarafından güncelleniyor. Lütfen biraz sonra tekrar deneyin."


class SharedDataManager:
    def __init__(self, profile_manager: ProfileManager):
        self.profile_manager = profile_manager
        self.shared_dir = get_local_root(self.profile_manager.data_root) / "shared"
        self.products_db = self.shared_dir / "products_master.db"
        self.customers_db = self.shared_dir / "customers_master.db"
        self.stock_db = self.shared_dir / "stock_adjustments.db"
        self.pending_dir = self.shared_dir / "customers_pending"
        self.locks_dir = self.shared_dir / "locks"
        self.ensure_layout()

    def refresh_paths(self) -> None:
        self.shared_dir = get_local_root(self.profile_manager.data_root) / "shared"
        self.products_db = self.shared_dir / "products_master.db"
        self.customers_db = self.shared_dir / "customers_master.db"
        self.stock_db = self.shared_dir / "stock_adjustments.db"
        self.pending_dir = self.shared_dir / "customers_pending"
        self.locks_dir = self.shared_dir / "locks"
        self.ensure_layout()

    def ensure_layout(self) -> None:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        self._init_products()
        self._init_customers()
        self._init_stock_adjustments()

    def add_product(self, data: dict, actor: str) -> None:
        with self._lock("products_master", actor):
            now = datetime.now().isoformat(timespec="seconds")
            with closing(sqlite3.connect(str(self.products_db))) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO products(name, category, price, stock, active, icon, created_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["name"].strip(),
                        data["category"].strip(),
                        float(data["price"]),
                        float(data.get("stock", 0)),
                        int(data.get("active", 1)),
                        data.get("icon", ""),
                        now,
                    ),
                )

    def update_product(self, product_id: int, data: dict, actor: str) -> None:
        with self._lock("products_master", actor):
            with closing(sqlite3.connect(str(self.products_db))) as conn, conn:
                conn.execute(
                    """
                    UPDATE products
                    SET name = ?, category = ?, price = ?, stock = ?, active = ?, icon = ?
                    WHERE id = ?
                    """,
                    (
                        data["name"].strip(),
                        data["category"].strip(),
                        float(data["price"]),
                        float(data.get("stock", 0)),
                        int(data.get("active", 1)),
                        data.get("icon", ""),
                        int(product_id),
                    ),
                )

    def delete_product(self, product_id: int, actor: str) -> None:
        with self._lock("products_master", actor):
            with closing(sqlite3.connect(str(self.products_db))) as conn, conn:
                conn.execute("UPDATE products SET active = 0 WHERE id = ?", (int(product_id),))

    def sync_products_to_local(self, local_db_path: str) -> None:
        self._copy_products_into_local(Path(local_db_path))

    def add_customer_master(self, data: dict, actor: str, cashier_id: int = 0) -> str:
        customer_uuid = data.get("customer_uuid") or str(uuid.uuid4())
        with self._lock("customers_master", actor):
            with closing(sqlite3.connect(str(self.customers_db))) as conn, conn:
                existing = conn.execute("SELECT customer_uuid FROM customers WHERE customer_uuid = ?", (customer_uuid,)).fetchone()
                if existing:
                    return customer_uuid
                now = data.get("created_at") or datetime.now().isoformat(timespec="seconds")
                conn.execute(
                    """
                    INSERT INTO customers(customer_uuid, name, phone, avatar, balance, credit_limit, note, cashier_id, created_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        customer_uuid,
                        data.get("name", "").strip(),
                        data.get("phone", "").strip(),
                        data.get("avatar", "").strip(),
                        float(data.get("balance", 0)),
                        float(data.get("credit_limit", -150)),
                        data.get("note", "").strip(),
                        int(cashier_id or data.get("cashier_id") or 0),
                        now,
                    ),
                )
        return customer_uuid

    def append_pending_customer(self, cashier_username: str, customer: dict) -> None:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        path = self.pending_dir / f"{cashier_username}_customers.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(customer, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def merge_pending_customers(self, actor: str = "sync") -> int:
        merged = 0
        for path in sorted(self.pending_dir.glob("*_customers.jsonl")):
            rows = []
            try:
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except (OSError, json.JSONDecodeError):
                continue
            for row in rows:
                self.add_customer_master(row, actor, cashier_id=int(row.get("cashier_id") or 0))
                merged += 1
            archive = path.with_suffix(path.suffix + f".merged_{datetime.now().strftime('%Y%m%d%H%M%S')}")
            try:
                os.replace(path, archive)
            except OSError:
                pass
        return merged

    def find_similar_customer_by_phone(self, phone: str) -> list[dict]:
        phone = (phone or "").strip()
        if not phone:
            return []
        with closing(sqlite3.connect(str(self.customers_db))) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM customers WHERE phone = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1 LIMIT 5",
                (phone,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_stock_adjustment(self, product_id: int, quantity: float, note: str, actor: str) -> None:
        with self._lock("stock_adjustments", actor):
            with closing(sqlite3.connect(str(self.stock_db))) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO stock_adjustments(product_id, quantity, note, actor, created_at)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (int(product_id), float(quantity), note.strip(), actor, datetime.now().isoformat(timespec="seconds")),
                )

    def effective_stock_map(self) -> dict[int, float]:
        products: dict[int, float] = {}
        with closing(sqlite3.connect(str(self.products_db))) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT id, stock FROM products WHERE active = 1 AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"):
                products[int(row["id"])] = float(row["stock"] or 0)
        with closing(sqlite3.connect(str(self.stock_db))) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT product_id, COALESCE(SUM(quantity), 0) AS total FROM stock_adjustments GROUP BY product_id"):
                products[int(row["product_id"])] = products.get(int(row["product_id"]), 0.0) + float(row["total"] or 0)
        for sales_db in get_local_root(self.profile_manager.data_root).glob("*/db/sales.db"):
            try:
                with closing(sqlite3.connect(f"file:{sales_db.as_posix()}?mode=ro", uri=True)) as conn:
                    conn.row_factory = sqlite3.Row
                    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "sale_items" not in tables:
                        continue
                    for row in conn.execute("SELECT product_id, COALESCE(SUM(quantity), 0) AS sold FROM sale_items GROUP BY product_id"):
                        products[int(row["product_id"])] = products.get(int(row["product_id"]), 0.0) - float(row["sold"] or 0)
            except Exception:
                continue
        return products

    def _copy_products_into_local(self, local_db: Path) -> None:
        local_db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(self.products_db))) as src, closing(sqlite3.connect(str(local_db))) as dst, dst:
            src.row_factory = sqlite3.Row
            rows = src.execute("SELECT * FROM products").fetchall()
            dst.execute("DELETE FROM products WHERE cashier_id = 0")
            for row in rows:
                archived = row["archived"] if "archived" in row.keys() else 0
                is_active = row["is_active"] if "is_active" in row.keys() else 1
                dst.execute(
                    """
                    INSERT OR REPLACE INTO products(id, name, category, price, stock, active, icon, created_at, cashier_id, archived, is_active)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        row["id"],
                        row["name"],
                        row["category"],
                        row["price"],
                        row["stock"],
                        row["active"],
                        row["icon"],
                        row["created_at"],
                        archived,
                        is_active,
                    ),
                )

    def _init_products(self) -> None:
        with closing(sqlite3.connect(str(self.products_db))) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    price REAL NOT NULL,
                    stock REAL DEFAULT 0,
                    active INTEGER DEFAULT 1,
                    icon TEXT DEFAULT '',
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(conn, "products", {"archived": "INTEGER DEFAULT 0", "is_active": "INTEGER DEFAULT 1"})

    def bootstrap_products_from_local(self, local_db_path: str) -> None:
        if not Path(local_db_path).exists():
            return
        with closing(sqlite3.connect(str(self.products_db))) as conn:
            count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count:
            return
        with closing(sqlite3.connect(str(local_db_path))) as src:
            src.row_factory = sqlite3.Row
            try:
                rows = src.execute("SELECT name, category, price, stock, active, icon, created_at FROM products ORDER BY id").fetchall()
            except sqlite3.Error:
                return
        if not rows:
            return
        with self._lock("products_master", "bootstrap"):
            with closing(sqlite3.connect(str(self.products_db))) as dst, dst:
                for row in rows:
                    dst.execute(
                        """
                        INSERT INTO products(name, category, price, stock, active, icon, created_at)
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (row["name"], row["category"], row["price"], row["stock"], row["active"], row["icon"], row["created_at"]),
                    )

    def _init_customers(self) -> None:
        with closing(sqlite3.connect(str(self.customers_db))) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_uuid TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT DEFAULT '',
                    avatar TEXT DEFAULT '',
                    balance REAL DEFAULT 0,
                    credit_limit REAL DEFAULT -150,
                    note TEXT DEFAULT '',
                    cashier_id INTEGER DEFAULT 0,
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(conn, "customers", {"archived": "INTEGER DEFAULT 0", "is_active": "INTEGER DEFAULT 1"})

    def _init_stock_adjustments(self) -> None:
        with closing(sqlite3.connect(str(self.stock_db))) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_adjustments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    quantity REAL NOT NULL,
                    note TEXT DEFAULT '',
                    actor TEXT DEFAULT '',
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(conn, "stock_adjustments", {"archived": "INTEGER DEFAULT 0", "is_active": "INTEGER DEFAULT 1"})

    @staticmethod
    def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _lock(self, name: str, actor: str):
        return _FileLock(self.locks_dir / f"{name}.lock", actor)


class _FileLock:
    def __init__(self, path: Path, actor: str):
        self.path = path
        self.actor = actor

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                created = datetime.fromisoformat(data.get("created_at", ""))
                if datetime.now() - created <= timedelta(seconds=LOCK_TIMEOUT_SECONDS):
                    raise RuntimeError(LOCK_MESSAGE)
            except RuntimeError:
                raise
            except Exception:
                pass
            try:
                self.path.unlink()
            except OSError:
                raise RuntimeError(LOCK_MESSAGE)
        payload = {
            "profile": self.actor,
            "computer": socket.gethostname(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            atomic_write_json(self.path, payload)
        except OSError:
            raise RuntimeError(LOCK_MESSAGE)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
