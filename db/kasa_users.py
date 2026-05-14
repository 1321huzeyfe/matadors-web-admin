# -*- coding: utf-8 -*-
import os
import sqlite3
import traceback
from contextlib import closing
from datetime import datetime
from .auth import AuthDatabase
from services.supabase_sync import safe_upsert_row_from_sqlite

class KasaUserMixin:
    # Authentication delegated to separate auth_db
    def authenticate(self, username: str, password: str):
        """Authenticate using separate auth database."""
        return self.auth_db.authenticate(username, password)

    def get_user_by_id(self, user_id: int):
        """Get user by ID from auth database."""
        return self.auth_db.get_user_by_id(user_id)

    def list_users(self):
        """List all users from auth database."""
        return self.auth_db.list_users()

    def list_cashiers(self):
        """List all cashiers from auth database."""
        return self.auth_db.list_cashiers()

    def update_user_password(self, username: str, new_password: str):
        """Update password in auth database and sync to main db."""
        username = username.strip()
        self.auth_db.update_user_password(username, new_password)
        # Sync user info to main db
        self._sync_user_from_auth(username)

    def _sync_user_from_auth(self, username: str):
        """Sync user from auth_db to main db."""
        user = next((u for u in self.auth_db.list_users(include_archived=True) if u["username"] == username), None)
        if user:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO users(id, username, user_type, full_name, email, archived, is_active)
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
            safe_upsert_row_from_sqlite(self.db_path, "users", user["id"])

    def create_cashier(self, username: str, full_name: str, password: str):
        """Create cashier in auth database only.

        The application layer creates the isolated kasa folder/database so a new
        cashier starts with empty product and customer files.
        """
        # Add to auth database
        self.auth_db.add_cashier(username, password, full_name)
        self._sync_user_from_auth(username.strip())

    def reset_all_passwords(self):
        """Reset all passwords to defaults in auth database."""
        self.auth_db.reset_all_passwords()
        # Sync all users to main db
        for user in self.auth_db.list_users():
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO users(id, username, user_type, full_name, email)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (user["id"], user["username"], user["user_type"], user["full_name"], user["email"]),
                )
            safe_upsert_row_from_sqlite(self.db_path, "users", user["id"])

    def update_cashier_profile(self, cashier_id: int, username: str, full_name: str):
        username = username.strip()
        full_name = full_name.strip()
        if not username or not full_name:
            raise ValueError("Kullanici adi ve kasa adi zorunlu.")
        self.auth_db.update_cashier_profile(cashier_id, username, full_name)
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                """
                UPDATE users SET username = ?, full_name = ?
                WHERE id = ? AND user_type = 'cashier'
                """,
                (username, full_name, cashier_id),
            )
            if cur.rowcount == 0:
                raise ValueError("Kasa kullanicisi bulunamadi.")
        self._sync_user_from_auth(username)

    def update_cashier_password_by_id(self, cashier_id: int, new_password: str):
        """Update cashier password in auth database."""
        if len(new_password) < 6:
            raise ValueError("Sifre en az 6 karakter olmali.")
        user = self.get_user_by_id(cashier_id)
        if not user or user["user_type"] != "cashier":
            raise ValueError("Kasa kullanicisi bulunamadi.")
        self.auth_db.update_user_password(user["username"], new_password)
        self._sync_user_from_auth(user["username"])

    def delete_cashier(self, cashier_id: int):
        """Soft-disable a cashier while preserving all historical data."""
        user = self.get_user_by_id(cashier_id)
        if user and user["user_type"] == "cashier":
            self.auth_db.delete_cashier(user["username"])
        else:
            raise ValueError("Kasa kullanicisi bulunamadi.")

        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE users SET archived = 1, is_active = 0 WHERE id = ? AND user_type = 'cashier'",
                (cashier_id,)
            )
            if cur.rowcount == 0:
                raise ValueError("Kasa kullanicisi bulunamadi veya pasiflestirilemedi.")
        safe_upsert_row_from_sqlite(self.db_path, "users", cashier_id)
