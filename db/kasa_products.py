# -*- coding: utf-8 -*-
import os
import sqlite3
import threading
import traceback
from contextlib import closing
from datetime import datetime
from .auth import AuthDatabase
from .cashier import CashierDatabase
from services.supabase_sync import safe_upsert_row_from_sqlite, safe_upsert_sale_with_items
from performance import measure

class KasaProductSaleMixin:
    def _can_manage_products(self) -> bool:
        return getattr(self, "active_role", "admin") in ("admin", "cashier")

    def _queue_product_sync(self, product_id: int) -> None:
        def worker():
            safe_upsert_row_from_sqlite(self.db_path, "products", product_id)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            safe_upsert_row_from_sqlite(self.db_path, "products", product_id)

    def _queue_sale_sync(self, sale_id: int, customer_id: int | None = None) -> None:
        def worker():
            safe_upsert_sale_with_items(self.db_path, sale_id)
            if customer_id:
                safe_upsert_row_from_sqlite(self.db_path, "customers", customer_id)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            safe_upsert_sale_with_items(self.db_path, sale_id)
            if customer_id:
                safe_upsert_row_from_sqlite(self.db_path, "customers", customer_id)

    @measure("urun_verisi_yukleme_suresi", lambda self, category=None, cashier_id=None, include_archived=False: f"category={category or ''} cashier_id={cashier_id}")
    def list_products(self, category: str | None = None, cashier_id: int = None, include_archived: bool = False):
        """List active products. Strict isolation - only show specified cashier's products."""
        q = "SELECT * FROM products WHERE active = 1"
        params: list = []
        if not include_archived:
            q += " AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
        if cashier_id is not None:
            q += " AND cashier_id = ?"
            params.append(cashier_id)
        if category and category != "Tüm Ürünler":
            q += " AND category = ?"
            params.append(category)
        q += " ORDER BY category, name COLLATE NOCASE"
        with closing(self._connect()) as conn:
            rows = conn.execute(q, params).fetchall()
        return [dict(row) for row in rows]

    @measure("urun_verisi_yukleme_suresi", lambda self, active_only=True, cashier_id=None, include_archived=False: f"all active_only={active_only} cashier_id={cashier_id}")
    def list_all_products(self, active_only: bool = True, cashier_id: int = None, include_archived: bool = False):
        """List all products with strict cashier isolation and optimized query."""
        with closing(self._connect()) as conn:
            # Use indexed columns for better performance
            q = """
            SELECT id, name, category, price, stock, active, icon, created_at, cashier_id, archived, is_active
            FROM products
            """
            params = []
            conditions = []
            
            if active_only:
                conditions.append("active = 1")
            if not include_archived:
                conditions.append("COALESCE(archived, 0) = 0")
                conditions.append("COALESCE(is_active, 1) = 1")
            if cashier_id is not None:
                conditions.append("cashier_id = ?")
                params.append(cashier_id)
            
            if conditions:
                q += " WHERE " + " AND ".join(conditions)
            
            q += " ORDER BY name COLLATE NOCASE"
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    @measure("urun_arama_suresi", lambda self, cashier_id=None: f"categories cashier_id={cashier_id}")
    def get_product_categories(self, cashier_id: int = None):
        """Get product categories. Strict isolation - only show categories for specified cashier's products."""
        q = "SELECT DISTINCT category FROM products WHERE active = 1 AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
        params: list = []
        if cashier_id is not None:
            q += " AND cashier_id = ?"
            params.append(cashier_id)
        q += " ORDER BY category COLLATE NOCASE"
        with closing(self._connect()) as conn:
            rows = conn.execute(q, params).fetchall()
        return ["Tüm Ürünler"] + [r["category"] for r in rows]

    @measure("urun_kayit_suresi", lambda self, name, category, price, stock, icon="", cashier_id=0, product_id=None: f"add cashier_id={cashier_id}")
    def add_product(self, name: str, category: str, price: float, stock: float, icon: str = "", cashier_id: int = 0, product_id: int = None):
        if not self._can_manage_products():
            raise ValueError("Urun ekleme yetkiniz yok.")
            raise ValueError("Ürün ekleme sadece yönetici tarafından yapılabilir.")
        if cashier_id is None:
            raise ValueError("Urun eklemek icin once ilgili kasa secilmeli.")
        name = (name or "").strip()
        category = (category or "").strip()
        price = float(price)
        stock = float(stock)
        if not name:
            raise ValueError("Ürün adı zorunlu.")
        if not category:
            raise ValueError("Kategori zorunlu.")
        if price < 0:
            raise ValueError("Fiyat negatif olamaz.")
        if stock < 0:
            raise ValueError("Stok negatif olamaz.")
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            if product_id is not None:
                # Insert with specific ID
                conn.execute(
                    """
                    INSERT INTO products(id, name, category, price, stock, icon, created_at, cashier_id)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (product_id, name, category, price, stock, icon, now, cashier_id),
                )
                pid = product_id
            else:
                # Insert with auto-generated ID
                cur = conn.execute(
                    """
                    INSERT INTO products(name, category, price, stock, icon, created_at, cashier_id)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, category, price, stock, icon, now, cashier_id),
                )
                pid = cur.lastrowid
        self._queue_product_sync(pid)

    def get_product(self, product_id: int, cashier_id: int = None):
        """Get product by ID. If cashier_id provided, verify ownership."""
        with closing(self._connect()) as conn:
            if cashier_id is not None:
                row = conn.execute(
                    "SELECT * FROM products WHERE id = ? AND cashier_id = ?",
                    (product_id, cashier_id)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM products WHERE id = ?",
                    (product_id,)
                ).fetchone()
        return dict(row) if row else None

    @measure("urun_kayit_suresi", lambda self, product_id, *args, **kwargs: f"update product_id={product_id}")
    def update_product(self, product_id: int, name: str, category: str, price: float, stock: float, active: int = 1, icon: str = "", cashier_id: int = None):
        """Update product. If cashier_id provided, verify ownership before update."""
        if not self._can_manage_products():
            raise ValueError("Urun duzenleme yetkiniz yok.")
            raise ValueError("Ürün düzenleme sadece yönetici tarafından yapılabilir.")
        if cashier_id is None:
            raise ValueError("Urun duzenlemek icin once ilgili kasa secilmeli.")
        name = (name or "").strip()
        category = (category or "").strip()
        price = float(price)
        stock = float(stock)
        if not name:
            raise ValueError("Ürün adı zorunlu.")
        if not category:
            raise ValueError("Kategori zorunlu.")
        if price < 0:
            raise ValueError("Fiyat negatif olamaz.")
        if stock < 0:
            raise ValueError("Stok negatif olamaz.")
        with closing(self._connect()) as conn, conn:
            if cashier_id is not None:
                # Verify this product belongs to the cashier
                verify = conn.execute(
                    "SELECT id FROM products WHERE id = ? AND cashier_id = ?",
                    (product_id, cashier_id)
                ).fetchone()
                if not verify:
                    raise ValueError("Urun bulunamadi veya erisim izniniz yok.")
            owner_clause = " AND cashier_id = ?" if cashier_id is not None else ""
            params = [name, category, price, stock, int(active), icon, product_id]
            if cashier_id is not None:
                params.append(cashier_id)
            conn.execute(
                f"""
                UPDATE products SET name = ?, category = ?, price = ?, stock = ?, active = ?, icon = ?
                WHERE id = ?{owner_clause}
                """,
                params,
            )
        self._queue_product_sync(product_id)

    def delete_product(self, product_id: int, cashier_id: int = None):
        """Soft-delete product. If cashier_id provided, verify ownership before update."""
        if not self._can_manage_products():
            raise ValueError("Urun pasiflestirme yetkiniz yok.")
            raise ValueError("Ürün silme sadece yönetici tarafından yapılabilir.")
        if cashier_id is None:
            raise ValueError("Urun pasiflestirmek icin once ilgili kasa secilmeli.")
        with closing(self._connect()) as conn, conn:
            if cashier_id is not None:
                # Verify this product belongs to the cashier
                verify = conn.execute(
                    "SELECT id FROM products WHERE id = ? AND cashier_id = ?",
                    (product_id, cashier_id)
                ).fetchone()
                if not verify:
                    raise ValueError("Urun bulunamadi veya erisim izniniz yok.")
            conn.execute(
                "UPDATE products SET active = 0, archived = 1, is_active = 0 WHERE id = ? AND cashier_id = ?",
                (product_id, cashier_id),
            )
        self._queue_product_sync(product_id)

    @measure("satis_kayit_suresi", lambda self, customer_id, cart_items, payment_method, cashier_id, note="", force_limit=False: f"method={payment_method} items={len(cart_items or [])} cashier_id={cashier_id}")
    def create_sale(
        self,
        customer_id: int | None,
        cart_items: list,
        payment_method: str,
        cashier_id: int,
        note: str = "",
        force_limit: bool = False,
    ):
        """Create sale with strict cashier isolation for products and customers."""
        if not cart_items:
            raise ValueError("Sepet bos.")
        now = datetime.now().isoformat(timespec="seconds")
        total = sum(item["quantity"] * item["price"] for item in cart_items)
        remaining_balance = None

        with closing(self._connect()) as conn, conn:
            cashier = conn.execute(
                "SELECT user_type FROM users WHERE id = ?",
                (cashier_id,),
            ).fetchone()
            if not cashier or cashier["user_type"] != "cashier":
                raise ValueError("Yönetici profili satış yapamaz.")

            # Verify all products exist in the local read-only product cache.
            for item in cart_items:
                product = conn.execute(
                    "SELECT id, stock FROM products WHERE id = ? AND cashier_id = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1",
                    (item["product_id"], cashier_id)
                ).fetchone()
                if not product:
                    raise ValueError(f"Urun bulunamadi veya erisim izniniz yok: {item.get('name', '')}")

            if payment_method == "DEFTER":
                if not customer_id:
                    raise ValueError("Defter satisi icin musteri secilmeli.")
                # Verify customer belongs to this cashier (strict isolation)
                customer = conn.execute(
                    "SELECT balance, credit_limit FROM customers WHERE id = ? AND cashier_id = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1",
                    (customer_id, cashier_id),
                ).fetchone()
                if not customer:
                    raise ValueError("Musteri bulunamadi veya erisim izniniz yok.")
                remaining_balance = customer["balance"] - total
                if remaining_balance < customer["credit_limit"] and not force_limit:
                    raise ValueError("LIMIT_CONFIRM_REQUIRED")

            cur = conn.execute(
                """
                INSERT INTO sales(customer_id, total, payment_method, note, created_at, cashier_id)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (customer_id, total, payment_method, note.strip(), now, cashier_id),
            )
            sale_id = cur.lastrowid

            for item in cart_items:
                line_total = item["quantity"] * item["price"]
                conn.execute(
                    """
                    INSERT INTO sale_items(sale_id, product_id, product_name, quantity, unit_price, line_total)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (sale_id, item["product_id"], item["name"], item["quantity"], item["price"], line_total),
                )
                conn.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ? AND cashier_id = ?",
                    (float(item["quantity"]), item["product_id"], cashier_id),
                )

            if payment_method == "DEFTER":
                # Update balance with cashier_id verification (strict isolation)
                cust_update = conn.execute(
                    "UPDATE customers SET balance = ? WHERE id = ? AND cashier_id = ?",
                    (remaining_balance, customer_id, cashier_id),
                )
                if cust_update.rowcount == 0:
                    raise ValueError("Musteri bakiyesi guncellenemedi - erisim izniniz yok.")
                conn.execute(
                    """
                    INSERT INTO balance_history(customer_id, amount, action_type, note, created_at)
                    VALUES(?, ?, 'SALE_DEFTER', ?, ?)
                    """,
                    (customer_id, -total, f"Defter satis #{sale_id}", now),
                )

        self._queue_sale_sync(sale_id, customer_id)
        return sale_id, total, remaining_balance
