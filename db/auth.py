# -*- coding: utf-8 -*-
import os
import hashlib
from contextlib import closing
from .base import Database
from path_utils import get_local_dir

class AuthDatabase(Database):
    """Separate database for password storage - isolated from application data."""

    def __init__(self, auth_db_path: str):
        super().__init__(auth_db_path)
        self._seed_default_passwords(force=False)

    def _connect_auth(self):
        return self._get_connection()

    def _init_db(self):
        """Override _init_db to initialize auth database instead of main database."""
        self._init_auth_db()

    def _init_auth_db(self):
        with closing(self._connect_auth()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    user_type TEXT NOT NULL CHECK(user_type IN ('admin', 'cashier')),
                    full_name TEXT NOT NULL,
                    email TEXT DEFAULT '',
                    archived INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1
                )
                """
            )
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(auth_users)").fetchall()}
            if "archived" not in cols:
                conn.execute("ALTER TABLE auth_users ADD COLUMN archived INTEGER DEFAULT 0")
            if "is_active" not in cols:
                conn.execute("ALTER TABLE auth_users ADD COLUMN is_active INTEGER DEFAULT 1")

    def _seed_default_passwords(self, force: bool = False):
        """Reset/seed default passwords."""
        with closing(self._connect_auth()) as conn, conn:
            # Default passwords
            admin_hash = self._hash_password("admin123")
            verb = "INSERT OR REPLACE" if force else "INSERT OR IGNORE"
            conn.execute(
                f"""
                {verb} INTO auth_users(id, username, password_hash, user_type, full_name, email, archived, is_active)
                VALUES(1, 'admin', ?, 'admin', 'Sistem Yoneticisi', '', 0, 1)
                """,
                (admin_hash,),
            )
            if force:
                conn.execute("DELETE FROM auth_users WHERE user_type = 'cashier' AND username = 'kasa1'")

    @staticmethod
    def _hash_password(password: str):
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def authenticate(self, username: str, password: str):
        """Authenticate user against separate auth database."""
        with closing(self._connect_auth()) as conn:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE username = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1",
                (username.strip(),),
            ).fetchone()
        if not row:
            return None
        if row["password_hash"] != self._hash_password(password):
            return None
        return dict(row)

    def get_user_by_id(self, user_id: int, include_archived: bool = False):
        """Get user by ID from auth database."""
        with closing(self._connect_auth()) as conn:
            active_filter = "" if include_archived else "AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
            row = conn.execute(
                f"SELECT * FROM auth_users WHERE id = ? {active_filter}",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_users(self, include_archived: bool = False):
        """List all users from auth database."""
        with closing(self._connect_auth()) as conn:
            where = "" if include_archived else "WHERE COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
            rows = conn.execute(
                f"SELECT id, username, user_type, full_name, email, archived, is_active FROM auth_users {where} ORDER BY user_type, username"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_cashiers(self, include_archived: bool = False):
        """List all cashiers from auth database."""
        with closing(self._connect_auth()) as conn:
            archived_filter = "" if include_archived else "AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
            rows = conn.execute(
                f"""
                SELECT id, username, user_type, full_name, email, archived, is_active
                FROM auth_users WHERE user_type = 'cashier' {archived_filter} ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_user_password(self, username: str, new_password: str):
        """Update password in auth database."""
        if len(new_password) < 6:
            raise ValueError("Sifre en az 6 karakter olmali.")
        with closing(self._connect_auth()) as conn, conn:
            cur = conn.execute(
                "UPDATE auth_users SET password_hash = ? WHERE username = ?",
                (self._hash_password(new_password), username),
            )
            if cur.rowcount == 0:
                raise ValueError("Kullanici bulunamadi.")

    def update_cashier_profile(self, cashier_id: int, username: str, full_name: str):
        """Update cashier username/full name in auth database."""
        username = username.strip()
        full_name = full_name.strip()
        if not username or not full_name:
            raise ValueError("Kullanici adi ve kasa adi zorunlu.")
        with closing(self._connect_auth()) as conn, conn:
            existing = conn.execute(
                "SELECT id FROM auth_users WHERE username = ? AND id != ?",
                (username, cashier_id),
            ).fetchone()
            if existing:
                raise ValueError("Bu kullanici adi zaten kullaniliyor.")
            cur = conn.execute(
                """
                UPDATE auth_users SET username = ?, full_name = ?
                WHERE id = ? AND user_type = 'cashier'
                """,
                (username, full_name, cashier_id),
            )
            if cur.rowcount == 0:
                raise ValueError("Kasa kullanicisi bulunamadi.")

    def add_cashier(self, username: str, password: str, full_name: str, email: str = ""):
        """Add new cashier to auth database."""
        if len(password) < 6:
            raise ValueError("Sifre en az 6 karakter olmali.")
        with closing(self._connect_auth()) as conn, conn:
            conn.execute(
                """
                INSERT INTO auth_users(username, password_hash, user_type, full_name, email, archived, is_active)
                VALUES(?, ?, 'cashier', ?, ?, 0, 1)
                """,
                (username.strip(), self._hash_password(password), full_name.strip(), email.strip()),
            )

    def delete_cashier(self, username: str):
        """Soft-disable cashier in auth database."""
        with closing(self._connect_auth()) as conn, conn:
            cur = conn.execute(
                "UPDATE auth_users SET archived = 1, is_active = 0 WHERE username = ? AND user_type = 'cashier'",
                (username.strip(),),
            )
            if cur.rowcount == 0:
                raise ValueError("Kasiyer pasifleştirilemedi.")

    def reset_all_passwords(self):
        """Reset all passwords to defaults."""
        self._seed_default_passwords(force=True)

    def get_cashier_database(self, username: str):
        """Get the individual database for a cashier."""
        cashier_db_path = os.path.join(get_local_dir(), f"{username.strip().lower()}.db")
        
        if os.path.exists(cashier_db_path):
            from .cashier import CashierDatabase
            return CashierDatabase(cashier_db_path)
        else:
            # Create if doesn't exist
            os.makedirs(os.path.dirname(cashier_db_path), exist_ok=True)
            from .cashier import CashierDatabase
            cashier_db = CashierDatabase(cashier_db_path)
            cashier_db._init_db()
            return cashier_db
