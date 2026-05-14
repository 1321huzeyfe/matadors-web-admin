# -*- coding: utf-8 -*-
import os
import sqlite3
import traceback
from contextlib import closing
from datetime import datetime
from .auth import AuthDatabase
from .cashier import CashierDatabase
from path_utils import get_kasa_db_path

class KasaCoreMixin:
    def __init__(self, db_path: str, auth_db_path: str = None):
        self.db_path = db_path
        # Initialize separate auth database
        if auth_db_path is None:
            # Default: same directory, _auth suffix
            base, ext = os.path.splitext(db_path)
            auth_db_path = f"{base}_auth{ext}"
        self.auth_db = AuthDatabase(auth_db_path)
        self._init_db()
    
    def get_cashier_database(self, username: str):
        """Get the individual database for a cashier."""
        cashier_db_path = str(get_kasa_db_path(username))
        
        if os.path.exists(cashier_db_path):
            return CashierDatabase(cashier_db_path)
        else:
            # Create if doesn't exist
            os.makedirs(os.path.dirname(cashier_db_path), exist_ok=True)
            cashier_db = CashierDatabase(cashier_db_path)
            cashier_db._init_db()
            return cashier_db

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self):
        with closing(self._connect()) as conn, conn:
            # Note: users/passwords now stored in separate auth database
            # Keep users table reference only for foreign key compatibility
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE,
                    user_type TEXT,
                    full_name TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_uuid TEXT UNIQUE,
                    name TEXT NOT NULL,
                    phone TEXT DEFAULT '',
                    avatar TEXT DEFAULT '',
                    balance REAL NOT NULL DEFAULT 0,
                    credit_limit REAL DEFAULT -150,
                    note TEXT DEFAULT '',
                    cashier_id INTEGER DEFAULT 0,
                    pending_sync INTEGER DEFAULT 1,
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    cashier_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    action_type TEXT NOT NULL CHECK(action_type IN ('load', 'spend')),
                    note TEXT DEFAULT '',
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                    FOREIGN KEY(cashier_id) REFERENCES users(id) ON DELETE RESTRICT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    price REAL NOT NULL,
                    stock REAL DEFAULT 0,
                    active INTEGER DEFAULT 1,
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    icon TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            # Migration: add icon column if not exists (for existing databases)
            try:
                conn.execute("ALTER TABLE products ADD COLUMN icon TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # Column already exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER,
                    cashier_id INTEGER NOT NULL,
                    total REAL NOT NULL,
                    payment_method TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
                    FOREIGN KEY(cashier_id) REFERENCES users(id) ON DELETE RESTRICT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sale_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    line_total REAL NOT NULL,
                    FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS balance_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    action_type TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cashier_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    amount REAL NOT NULL,
                    note TEXT DEFAULT '',
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(cashier_id) REFERENCES users(id) ON DELETE RESTRICT
                )
                """
            )
            self._migrate_columns(conn)

        self._seed_defaults()

    def _migrate_columns(self, conn):
        def cols(table):
            return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

        # Migration: Check if old users table exists with password_hash (pre-auth_db separation)
        if "users" in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            u = cols("users")
            if "password_hash" in u:
                # Temporarily disable foreign keys for migration
                conn.execute("PRAGMA foreign_keys = OFF")
                try:
                    # Old table with passwords - migrate data and recreate without password_hash
                    old_users = conn.execute(
                        "SELECT id, username, user_type, full_name, email FROM users"
                    ).fetchall()
                    # Rename old table instead of drop (safer)
                    conn.execute("ALTER TABLE users RENAME TO users_old")
                    # Create new users table without password_hash
                    conn.execute(
                        """
                        CREATE TABLE users (
                            id INTEGER PRIMARY KEY,
                            username TEXT UNIQUE,
                            user_type TEXT,
                            full_name TEXT DEFAULT '',
                            email TEXT DEFAULT '',
                            archived INTEGER DEFAULT 0,
                            is_active INTEGER DEFAULT 1
                        )
                        """
                    )
                    # Re-insert users without passwords (passwords now in auth_db)
                    # Use simple INSERT to preserve foreign key relationships
                    for user in old_users:
                        try:
                            conn.execute(
                                """
                                INSERT INTO users(id, username, user_type, full_name, email, archived, is_active)
                                VALUES(?, ?, ?, ?, ?, 0, 1)
                                """,
                                (user["id"], user["username"], user["user_type"], user["full_name"], user["email"]),
                            )
                        except sqlite3.IntegrityError:
                            # User already exists, skip
                            pass
                    # Drop old table
                    conn.execute("DROP TABLE users_old")
                finally:
                    conn.execute("PRAGMA foreign_keys = ON")

        u = cols("users")
        if "archived" not in u:
            conn.execute("ALTER TABLE users ADD COLUMN archived INTEGER DEFAULT 0")
        if "is_active" not in u:
            conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")

        c = cols("customers")
        if "avatar" not in c:
            conn.execute("ALTER TABLE customers ADD COLUMN avatar TEXT DEFAULT ''")
        if "credit_limit" not in c:
            conn.execute("ALTER TABLE customers ADD COLUMN credit_limit REAL DEFAULT -150")
        if "note" not in c:
            conn.execute("ALTER TABLE customers ADD COLUMN note TEXT DEFAULT ''")
        # Migration: add cashier_id for multi-cashier isolation
        if "cashier_id" not in c:
            conn.execute("ALTER TABLE customers ADD COLUMN cashier_id INTEGER DEFAULT 0")
        if "customer_uuid" not in c:
            conn.execute("ALTER TABLE customers ADD COLUMN customer_uuid TEXT")
        if "pending_sync" not in c:
            conn.execute("ALTER TABLE customers ADD COLUMN pending_sync INTEGER DEFAULT 1")
        if "archived" not in c:
            conn.execute("ALTER TABLE customers ADD COLUMN archived INTEGER DEFAULT 0")
        if "is_active" not in c:
            conn.execute("ALTER TABLE customers ADD COLUMN is_active INTEGER DEFAULT 1")

        p = cols("products")
        if "icon" not in p:
            conn.execute("ALTER TABLE products ADD COLUMN icon TEXT DEFAULT ''")
        # Migration: add cashier_id for multi-cashier isolation
        if "cashier_id" not in p:
            conn.execute("ALTER TABLE products ADD COLUMN cashier_id INTEGER DEFAULT 0")
        if "archived" not in p:
            conn.execute("ALTER TABLE products ADD COLUMN archived INTEGER DEFAULT 0")
        if "is_active" not in p:
            conn.execute("ALTER TABLE products ADD COLUMN is_active INTEGER DEFAULT 1")

        if "sales" in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            s = cols("sales")
            if "cashier_id" not in s:
                conn.execute("ALTER TABLE sales ADD COLUMN cashier_id INTEGER")
                # Get first cashier from auth_db or use 1 as fallback
                try:
                    cashiers = self.auth_db.list_cashiers()
                    fallback = cashiers[0]["id"] if cashiers else 1
                except:
                    fallback = 1
                conn.execute("UPDATE sales SET cashier_id = ? WHERE cashier_id IS NULL", (fallback,))
            if "archived" not in s:
                conn.execute("ALTER TABLE sales ADD COLUMN archived INTEGER DEFAULT 0")
            if "is_active" not in s:
                conn.execute("ALTER TABLE sales ADD COLUMN is_active INTEGER DEFAULT 1")

        for table in ("transactions", "expenses"):
            if table in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
                table_cols = cols(table)
                if "archived" not in table_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN archived INTEGER DEFAULT 0")
                if "is_active" not in table_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN is_active INTEGER DEFAULT 1")

    def _seed_defaults(self):
        with closing(self._connect()) as conn, conn:
            # Sync users from auth_db (no passwords stored here)
            # First check if we have any users in auth_db
            auth_users = self.auth_db.list_users(include_archived=True)
            if not auth_users:
                # Auth db is empty, seed it first
                self.auth_db._seed_default_passwords()
                auth_users = self.auth_db.list_users(include_archived=True)

            # Use INSERT OR IGNORE to avoid REPLACE which can break foreign keys
            for user in auth_users:
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO users(id, username, user_type, full_name, email, archived, is_active)
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user["id"],
                            user["username"],
                            user["user_type"],
                            user["full_name"],
                            user["email"],
                            int(user.get("archived", 0) or 0),
                            int(user.get("is_active", 1) if user.get("is_active") is not None else 1),
                        ),
                    )
                    # Update existing user without breaking foreign keys
                    conn.execute(
                        """
                        UPDATE users SET username = ?, user_type = ?, full_name = ?, email = ?, archived = ?, is_active = ?
                        WHERE id = ?
                        """,
                        (
                            user["username"],
                            user["user_type"],
                            user["full_name"],
                            user["email"],
                            int(user.get("archived", 0) or 0),
                            int(user.get("is_active", 1) if user.get("is_active") is not None else 1),
                            user["id"],
                        ),
                    )
                except sqlite3.Error:
                    # Skip if any error (user might already exist with different constraints)
                    pass

            defaults = {
                "admin_email": "",
                "fernet_key": "",
                "drive_folder_id": "",
                "service_account_json": "",
                "ui_theme": "matador",
                "app_title": "Matadors Club",
                "initial_setup_done": "0",
            }
            for key, value in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO app_settings(key, value) VALUES(?, ?)",
                    (key, value),
                )

    def reset_to_clean_state(self):
        """Clear transactional data while keeping schema and the admin account."""
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM sale_items")
            conn.execute("DELETE FROM sales")
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM balance_history")
            conn.execute("DELETE FROM expenses")
            conn.execute("DELETE FROM customers")
            conn.execute("DELETE FROM products")
            conn.execute("DELETE FROM users WHERE user_type = 'cashier'")
            conn.execute("UPDATE app_settings SET value = '0' WHERE key = 'initial_setup_done'")
        try:
            for user in list(self.auth_db.list_cashiers()):
                self.auth_db.delete_cashier(user["username"])
        except Exception:
            pass
