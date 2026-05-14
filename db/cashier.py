# -*- coding: utf-8 -*-
import os
from contextlib import closing
from .base import Database
from path_utils import get_kasa_db_path
from services.supabase_sync import safe_upsert_row_from_sqlite, safe_upsert_sale_with_items

class CashierDatabase(Database):
    """Individual database for each cashier with their own data."""
    
    def __init__(self, db_path: str):
        super().__init__(db_path)
    
    def _init_db(self):
        """Initialize database tables for individual cashier."""
        with closing(self._connect()) as conn, conn:
            # Create tables for individual cashier data
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT,
                    balance REAL DEFAULT 0,
                    credit_limit REAL DEFAULT -150,
                    avatar TEXT,
                    note TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price REAL NOT NULL,
                    stock REAL DEFAULT 0,
                    active INTEGER DEFAULT 1,
                    icon TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER,
                    total REAL NOT NULL,
                    payment_method TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES customers (id)
                )
                """
            )
            
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sale_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL,
                    product_id INTEGER,
                    product_name TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    unit_price REAL NOT NULL,
                    line_total REAL NOT NULL,
                    FOREIGN KEY (sale_id) REFERENCES sales (id)
                )
                """
            )
            
            # Add product_id column if it doesn't exist (migration for existing databases)
            try:
                conn.execute("SELECT product_id FROM sale_items LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE sale_items ADD COLUMN product_id INTEGER")
            
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER,
                    amount REAL NOT NULL,
                    action_type TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES customers (id)
                )
                """
            )
            
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
    
    def _add_default_products(self):
        """Legacy hook kept for compatibility; new cashiers start empty."""
        return
    
    def migrate_existing_cashiers(self):
        """Migrate existing cashiers to individual databases."""
        # Get all existing cashiers
        cashiers = self.list_cashiers()
        
        for cashier in cashiers:
            username = cashier["username"]
            
            cashier_db_path = str(get_kasa_db_path(username))
            
            if not os.path.exists(cashier_db_path):
                # Initialize new database
                cashier_db = CashierDatabase(cashier_db_path)
                cashier_db._init_db()
                
                # Migrate existing data for this cashier
                self._migrate_cashier_data(username, cashier_db)
    
    def _migrate_cashier_data(self, username: str, cashier_db: 'CashierDatabase'):
        """Migrate existing data for a specific cashier."""
        cashier_id = None
        for c in self.list_cashiers():
            if c["username"] == username:
                cashier_id = c["id"]
                break
        
        if not cashier_id:
            return
        
        # Migrate customers
        customers = self._get_customers_by_cashier(cashier_id)
        for customer in customers:
            cashier_db._add_customer(customer)
        
        # Migrate products
        products = self._get_products_by_cashier(cashier_id)
        for product in products:
            cashier_db._add_product(product)
        
        # Migrate sales and transactions
        sales = self._get_sales_by_cashier(cashier_id)
        for sale in sales:
            cashier_db._add_sale(sale)
    
    def _get_customers_by_cashier(self, cashier_id: int):
        """Get customers for a specific cashier from main database."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM customers WHERE cashier_id = ?",
                (cashier_id,)
            ).fetchall()
        return [dict(row) for row in rows]
    
    def _get_products_by_cashier(self, cashier_id: int):
        """Get products for a specific cashier from main database."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM products WHERE cashier_id = ?",
                (cashier_id,)
            ).fetchall()
        return [dict(row) for row in rows]
    
    def _get_sales_by_cashier(self, cashier_id: int):
        """Get sales for a specific cashier from main database."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM sales WHERE cashier_id = ?",
                (cashier_id,)
            ).fetchall()
        return [dict(row) for row in rows]
    
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
    
    def get_product_categories(self, cashier_id: int = None):
        """Get product categories. For individual database, cashier_id is not used."""
        q = "SELECT DISTINCT category FROM products WHERE active = 1 AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
        q += " ORDER BY category COLLATE NOCASE"
        with closing(self._connect()) as conn:
            rows = conn.execute(q).fetchall()
        return ["Tüm Ürünler"] + [r["category"] for r in rows]
    
    def list_products(self, category: str | None = None, cashier_id: int = None, include_archived: bool = False):
        """List active products. For individual database, cashier_id is not used."""
        q = "SELECT * FROM products WHERE active = 1"
        params: list = []
        if not include_archived:
            q += " AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
        if category and category != "Tüm Ürünler":
            q += " AND category = ?"
            params.append(category)
        q += " ORDER BY category, name COLLATE NOCASE"
        with closing(self._connect()) as conn:
            rows = conn.execute(q, params).fetchall()
        return [dict(row) for row in rows]
    
    def create_sale(
        self,
        customer_id: int | None,
        cart_items: list,
        payment_method: str,
        cashier_id: int,
        note: str = "",
        force_limit: bool = False,
    ):
        """Create sale for individual database (cashier_id not used in individual DB)."""
        if not cart_items:
            raise ValueError("Sepet bos.")
        now = datetime.now().isoformat(timespec="seconds")
        total = sum(item["quantity"] * item["price"] for item in cart_items)
        remaining_balance = None

        with closing(self._connect()) as conn, conn:
            # Check customer balance for defter sales
            if payment_method == "DEFTER" and customer_id:
                cur = conn.cursor()
                cur.execute("SELECT balance, credit_limit FROM customers WHERE id = ?", (customer_id,))
                row = cur.fetchone()
                if row:
                    balance, credit_limit = row
                    predicted_balance = balance - total
                    if predicted_balance < credit_limit and not force_limit:
                        raise ValueError("LIMIT_CONFIRM_REQUIRED")
                    remaining_balance = predicted_balance
            
            # Insert sale
            conn.execute(
                """
                INSERT INTO sales(customer_id, total, payment_method, note, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (customer_id, total, payment_method, note, now)
            )
            sale_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            
            # Insert sale items
            for item in cart_items:
                conn.execute(
                    """
                    INSERT INTO sale_items(sale_id, product_id, product_name, quantity, unit_price, line_total)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (sale_id, item.get("product_id"), item["name"], item["quantity"], item["price"], item["quantity"] * item["price"])
                )
                
            # Update customer balance if defter sale
            if payment_method == "DEFTER" and customer_id:
                conn.execute(
                    "UPDATE customers SET balance = ?, updated_at = ? WHERE id = ?",
                    (remaining_balance, now, customer_id)
                )

        safe_upsert_sale_with_items(self.db_path, sale_id)
        if customer_id:
            safe_upsert_row_from_sqlite(self.db_path, "customers", customer_id)
        return sale_id, total, remaining_balance
    
    def _add_customer(self, customer_data: dict):
        """Add customer to individual database."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO customers(name, phone, balance, credit_limit, avatar, note, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_data["name"],
                    customer_data.get("phone"),
                    customer_data.get("balance", 0),
                    customer_data.get("credit_limit", -150),
                    customer_data.get("avatar"),
                    customer_data.get("note"),
                    customer_data.get("created_at", datetime.now().isoformat()),
                    customer_data.get("updated_at", datetime.now().isoformat())
                )
            )
    
    def _add_product(self, product_data: dict):
        """Add product to individual database."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO products(name, category, price, stock, active, icon, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_data["name"],
                    product_data["category"],
                    product_data["price"],
                    product_data.get("stock", 0),
                    product_data.get("active", 1),
                    product_data.get("icon"),
                    product_data.get("created_at", datetime.now().isoformat())
                )
            )
    
    def _add_sale(self, sale_data: dict):
        """Add sale to individual database."""
        with closing(self._connect()) as conn, conn:
            # Insert sale
            cursor = conn.execute(
                """
                INSERT INTO sales(customer_id, total, payment_method, note, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    sale_data.get("customer_id"),
                    sale_data["total"],
                    sale_data["payment_method"],
                    sale_data.get("note"),
                    sale_data.get("created_at", datetime.now().isoformat())
                )
            )
            sale_id = cursor.lastrowid
            
            # Insert sale items if available
            if "items" in sale_data:
                for item in sale_data["items"]:
                    conn.execute(
                        """
                        INSERT INTO sale_items(sale_id, product_name, quantity, unit_price, line_total)
                        VALUES(?, ?, ?, ?, ?)
                        """,
                        (
                            sale_id,
                            item["product_name"],
                            item["quantity"],
                            item["unit_price"],
                            item["line_total"]
                        )
                    )
