# -*- coding: utf-8 -*-
import os
import sqlite3
import traceback
import uuid
from contextlib import closing
from datetime import datetime
from .auth import AuthDatabase
from .base import DEFAULT_PRODUCTS
from .cashier import CashierDatabase
from services.supabase_sync import safe_upsert_row_from_sqlite
from performance import measure

class KasaCustomerMixin:

    @measure("musteri_verisi_yukleme_suresi", lambda self, search_text="", cashier_id=None, include_archived=False: f"search={bool(str(search_text).strip())} cashier_id={cashier_id}")
    def list_customers(self, search_text: str = "", cashier_id: int = None, include_archived: bool = False):
        """List customers. If cashier_id provided, show only that cashier's customers."""
        where_clauses = []
        params = []
        if not include_archived:
            where_clauses.append("COALESCE(archived, 0) = 0")
            where_clauses.append("COALESCE(is_active, 1) = 1")
        if cashier_id is not None and cashier_id != 0:
            where_clauses.append("cashier_id = ?")
            params.append(cashier_id)
        if search_text.strip():
            like = f"%{search_text.strip()}%"
            where_clauses.append("(name LIKE ? OR phone LIKE ? OR avatar LIKE ? OR note LIKE ?)")
            params.extend([like, like, like, like])
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM customers {where} ORDER BY name COLLATE NOCASE",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    @measure("musteri_arama_suresi", lambda self, letter, cashier_id=None, include_archived=False: f"letter={letter} cashier_id={cashier_id}")
    def list_customers_startswith(self, letter: str, cashier_id: int = None, include_archived: bool = False):
        """List customers starting with letter. If cashier_id provided, filter by cashier."""
        where = "WHERE UPPER(name) LIKE ?"
        params = [f"{letter.upper()}%"]
        if not include_archived:
            where += " AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
        if cashier_id is not None and cashier_id != 0:
            where += " AND cashier_id = ?"
            params.append(cashier_id)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM customers {where} ORDER BY name COLLATE NOCASE",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_customer(self, customer_id: int, cashier_id: int = None):
        """Get customer by ID. If cashier_id provided, verify ownership."""
        with closing(self._connect()) as conn:
            if cashier_id is not None:
                row = conn.execute(
                    "SELECT * FROM customers WHERE id = ? AND cashier_id = ?",
                    (customer_id, cashier_id)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM customers WHERE id = ?",
                    (customer_id,)
                ).fetchone()
        return dict(row) if row else None

    @measure("musteri_kayit_suresi", lambda self, name, phone="", avatar="", opening_balance=0.0, credit_limit=-150.0, note="", cashier_id=0, customer_uuid=None: f"cashier_id={cashier_id}")
    def add_customer(
        self,
        name: str,
        phone: str = "",
        avatar: str = "",
        opening_balance: float = 0.0,
        credit_limit: float = -150.0,
        note: str = "",
        cashier_id: int = 0,
        customer_uuid: str = None,
    ):
        now = datetime.now().isoformat(timespec="seconds")
        customer_uuid = customer_uuid or str(uuid.uuid4())
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                """
                INSERT INTO customers(customer_uuid, name, phone, avatar, balance, credit_limit, note, created_at, cashier_id, pending_sync)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (customer_uuid, name.strip(), phone.strip(), avatar.strip(), float(opening_balance), float(credit_limit), note.strip(), now, cashier_id, 1),
            )
            cid = cur.lastrowid
            if opening_balance:
                conn.execute(
                    """
                    INSERT INTO balance_history(customer_id, amount, action_type, note, created_at)
                    VALUES(?, ?, 'OPENING', 'Acilis bakiyesi', ?)
                    """,
                    (cid, float(opening_balance), now),
                )
        safe_upsert_row_from_sqlite(self.db_path, "customers", cid)
        return cid

    @measure("musteri_kayit_suresi", lambda self, customer_id, *args, **kwargs: f"update customer_id={customer_id}")
    def update_customer(self, customer_id: int, name: str, phone: str, avatar: str, credit_limit: float, note: str, cashier_id: int = None):
        """Update customer. If cashier_id provided, verify ownership before update."""
        with closing(self._connect()) as conn, conn:
            if cashier_id is not None:
                # Verify this customer belongs to the cashier
                verify = conn.execute(
                    "SELECT id FROM customers WHERE id = ? AND cashier_id = ?",
                    (customer_id, cashier_id)
                ).fetchone()
                if not verify:
                    raise ValueError("Musteri bulunamadi veya erisim izniniz yok.")
            conn.execute(
                """
                UPDATE customers
                SET name = ?, phone = ?, avatar = ?, credit_limit = ?, note = ?
                WHERE id = ?
                """,
                (name.strip(), phone.strip(), avatar.strip(), float(credit_limit), note.strip(), customer_id),
            )
        safe_upsert_row_from_sqlite(self.db_path, "customers", customer_id)

    def delete_customer(self, customer_id: int, cashier_id: int = None):
        """Delete customer. If cashier_id provided, verify ownership before delete."""
        with closing(self._connect()) as conn, conn:
            if cashier_id is not None:
                # Verify this customer belongs to the cashier
                verify = conn.execute(
                    "SELECT id FROM customers WHERE id = ? AND cashier_id = ?",
                    (customer_id, cashier_id)
                ).fetchone()
                if not verify:
                    raise ValueError("Musteri bulunamadi veya erisim izniniz yok.")
            conn.execute("UPDATE sales SET customer_id = NULL WHERE customer_id = ?", (customer_id,))
            conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))

    @measure("musteri_kayit_suresi", lambda self, customer_id, *args, **kwargs: f"set_balance customer_id={customer_id}")
    def set_balance(self, customer_id: int, new_balance: float, note: str = "Bakiye duzenleme", cashier_id: int = None):
        """Set balance with cashier_id verification for strict isolation."""
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            if cashier_id is not None:
                # Verify this customer belongs to the cashier
                verify = conn.execute(
                    "SELECT balance FROM customers WHERE id = ? AND cashier_id = ?",
                    (customer_id, cashier_id)
                ).fetchone()
                if not verify:
                    raise ValueError("Musteri bulunamadi veya erisim izniniz yok.")
                cur = verify
            else:
                cur = conn.execute("SELECT balance FROM customers WHERE id = ?", (customer_id,)).fetchone()
                if not cur:
                    raise ValueError("Musteri bulunamadi.")
            diff = float(new_balance) - float(cur["balance"])
            conn.execute("UPDATE customers SET balance = ? WHERE id = ?", (float(new_balance), customer_id))
            conn.execute(
                """
                INSERT INTO balance_history(customer_id, amount, action_type, note, created_at)
                VALUES(?, ?, 'BALANCE_SET', ?, ?)
                """,
                (customer_id, diff, note, now),
            )
        safe_upsert_row_from_sqlite(self.db_path, "customers", customer_id)

    def recent_balance_history(self, customer_id: int, limit: int = 30, cashier_id: int = None):
        """Get balance history. If cashier_id provided, verify customer ownership."""
        with closing(self._connect()) as conn:
            if cashier_id is not None:
                # Verify customer belongs to this cashier
                verify = conn.execute(
                    "SELECT id FROM customers WHERE id = ? AND cashier_id = ?",
                    (customer_id, cashier_id)
                ).fetchone()
                if not verify:
                    raise ValueError("Musteri bulunamadi veya erisim izniniz yok.")
            rows = conn.execute(
                """
                SELECT amount, action_type, note, created_at FROM balance_history
                WHERE customer_id = ? ORDER BY id DESC LIMIT ?
                """,
                (customer_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    @measure("musteri_kayit_suresi", lambda self, customer_id, amount, action_type, cashier_id, note="": f"change_balance customer_id={customer_id} action={action_type}")
    def change_balance(self, customer_id: int, amount: float, action_type: str, cashier_id: int, note: str = ""):
        """Change balance with strict cashier isolation."""
        multiplier = 1 if action_type == "load" else -1
        final_amount = abs(float(amount)) * multiplier
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            # Verify customer belongs to this cashier (strict isolation)
            verify = conn.execute(
                "SELECT id FROM customers WHERE id = ? AND cashier_id = ?",
                (customer_id, cashier_id)
            ).fetchone()
            if not verify:
                raise ValueError("Musteri bulunamadi veya erisim izniniz yok.")

            customer_update = conn.execute(
                "UPDATE customers SET balance = balance + ? WHERE id = ? AND cashier_id = ?",
                (final_amount, customer_id, cashier_id),
            )
            if customer_update.rowcount == 0:
                raise ValueError("Musteri bulunamadi veya erisim izniniz yok.")
            conn.execute(
                """
                INSERT INTO transactions(customer_id, cashier_id, amount, action_type, note, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (customer_id, cashier_id, final_amount, action_type, note.strip(), now),
            )
            conn.execute(
                """
                INSERT INTO balance_history(customer_id, amount, action_type, note, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    final_amount,
                    "BALANCE_ADD" if action_type == "load" else "BALANCE_SPEND",
                    note.strip() or "Kasa islemi",
                    now,
                ),
            )
        safe_upsert_row_from_sqlite(self.db_path, "customers", customer_id)
