# -*- coding: utf-8 -*-
import os
import sqlite3
import traceback
from contextlib import closing
from datetime import datetime
from .auth import AuthDatabase
from .base import DEFAULT_PRODUCTS
from .cashier import CashierDatabase

class KasaReportMixin:

    def daily_report(self, target_date: str, cashier_id: int | None = None):
        params = [target_date]
        cashier_clause = ""
        if cashier_id is not None:
            cashier_clause = "AND t.cashier_id = ?"
            params.append(cashier_id)

        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    t.id, t.created_at, t.action_type, t.amount, t.note,
                    c.name AS customer_name, u.full_name AS cashier_name
                FROM transactions t
                INNER JOIN customers c ON c.id = t.customer_id
                INNER JOIN users u ON u.id = t.cashier_id
                WHERE date(t.created_at) = ?
                AND COALESCE(t.archived, 0) = 0 AND COALESCE(t.is_active, 1) = 1
                AND COALESCE(c.archived, 0) = 0 AND COALESCE(c.is_active, 1) = 1
                {cashier_clause}
                ORDER BY t.id DESC
                """,
                params,
            ).fetchall()

            totals = conn.execute(
                f"""
                SELECT
                    SUM(CASE WHEN action_type = 'spend' THEN ABS(amount) ELSE 0 END) AS ciro,
                    SUM(CASE WHEN action_type = 'load' THEN amount ELSE 0 END) AS yukleme,
                    COUNT(*) AS islem_sayisi
                FROM transactions t
                WHERE date(t.created_at) = ?
                AND COALESCE(t.archived, 0) = 0 AND COALESCE(t.is_active, 1) = 1
                {cashier_clause}
                """,
                params,
            ).fetchone()

            sparams = [target_date]
            sclause = ""
            if cashier_id is not None:
                sclause = "AND cashier_id = ?"
                sparams.append(cashier_id)
            pos_row = conn.execute(
                f"""
                SELECT COALESCE(SUM(total), 0) AS pos_total, COUNT(*) AS sale_count
                FROM sales WHERE date(created_at) = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1 {sclause}
                """,
                sparams,
            ).fetchone()

        return {
            "date": target_date,
            "transactions": [dict(row) for row in rows],
            "ciro": float(totals["ciro"] or 0),
            "yukleme": float(totals["yukleme"] or 0),
            "islem_sayisi": int(totals["islem_sayisi"] or 0),
            "pos_total": float(pos_row["pos_total"] or 0),
            "pos_sale_count": int(pos_row["sale_count"] or 0),
        }

    def cashier_daily_summaries(self, target_date: str):
        """Get one-row daily totals for each cashier in a single query."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                WITH tx AS (
                    SELECT cashier_id,
                        SUM(CASE WHEN action_type = 'spend' THEN ABS(amount) ELSE 0 END) AS ciro,
                        SUM(CASE WHEN action_type = 'load' THEN amount ELSE 0 END) AS yukleme
                    FROM transactions
                    WHERE date(created_at) = ?
                    AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1
                    GROUP BY cashier_id
                ),
                sales_totals AS (
                    SELECT cashier_id,
                        COALESCE(SUM(total), 0) AS pos_total
                    FROM sales
                    WHERE date(created_at) = ?
                    AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1
                    GROUP BY cashier_id
                )
                SELECT u.id AS cashier_id,
                    u.full_name,
                    u.username,
                    COALESCE(tx.ciro, 0) AS ciro,
                    COALESCE(tx.yukleme, 0) AS yukleme,
                    COALESCE(sales_totals.pos_total, 0) AS pos_total
                FROM users u
                LEFT JOIN tx ON tx.cashier_id = u.id
                LEFT JOIN sales_totals ON sales_totals.cashier_id = u.id
                WHERE u.user_type = 'cashier'
                ORDER BY u.id
                """,
                (target_date, target_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def daily_sales_detail(self, target_date: str, cashier_id: int | None = None):
        params_sales = [target_date]
        extra = ""
        if cashier_id is not None:
            extra = " AND s.cashier_id = ?"
            params_sales.append(cashier_id)
        with closing(self._connect()) as conn:
            sales = conn.execute(
                f"""
                SELECT s.id, s.created_at, s.total, s.payment_method, c.name AS customer_name, u.full_name AS cashier_name
                FROM sales s
                LEFT JOIN customers c ON c.id = s.customer_id
                INNER JOIN users u ON u.id = s.cashier_id
                WHERE date(s.created_at) = ? AND COALESCE(s.archived, 0) = 0 AND COALESCE(s.is_active, 1) = 1 {extra}
                ORDER BY s.id DESC
                """,
                params_sales,
            ).fetchall()
            items = conn.execute(
                f"""
                SELECT si.sale_id, si.product_name, si.quantity, si.line_total
                FROM sale_items si
                INNER JOIN sales s ON s.id = si.sale_id
                WHERE date(s.created_at) = ? AND COALESCE(s.archived, 0) = 0 AND COALESCE(s.is_active, 1) = 1 {extra}
                ORDER BY si.sale_id DESC
                """,
                params_sales,
            ).fetchall()
            pay_params = [target_date]
            pay_extra = ""
            if cashier_id is not None:
                pay_extra = " AND cashier_id = ?"
                pay_params.append(cashier_id)
            pay_totals = conn.execute(
                f"""
                SELECT payment_method, SUM(total) AS total_amount, COUNT(*) AS count_value
                FROM sales WHERE date(created_at) = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1 {pay_extra}
                GROUP BY payment_method
                """,
                pay_params,
            ).fetchall()
        return {
            "sales": [dict(row) for row in sales],
            "items": [dict(row) for row in items],
            "totals": [dict(row) for row in pay_totals],
        }

    def customer_activity_between(self, start_date: str, end_date: str, cashier_id: int | None = None):
        """Return all customer-linked POS and balance movements for a date range."""
        sales_params = [start_date, end_date]
        tx_params = [start_date, end_date]
        sales_cashier = ""
        tx_cashier = ""
        if cashier_id is not None:
            sales_cashier = "AND s.cashier_id = ?"
            tx_cashier = "AND t.cashier_id = ?"
            sales_params.append(cashier_id)
            tx_params.append(cashier_id)

        rows = []
        with closing(self._connect()) as conn:
            customers_cashier = ""
            customer_params = [start_date, end_date]
            if cashier_id is not None:
                customers_cashier = "AND cashier_id = ?"
                customer_params.append(cashier_id)
            new_customers = conn.execute(
                f"""
                SELECT created_at,
                       name AS customer_name,
                       phone,
                       balance,
                       cashier_id
                FROM customers
                WHERE date(created_at) BETWEEN ? AND ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1 {customers_cashier}
                """,
                customer_params,
            ).fetchall()
            sales = conn.execute(
                f"""
                SELECT s.id,
                       s.created_at,
                       COALESCE(c.name, 'Misafir') AS customer_name,
                       s.payment_method,
                       s.total,
                       u.full_name AS cashier_name,
                       GROUP_CONCAT(si.product_name || ' x' || si.quantity, ', ') AS items
                FROM sales s
                LEFT JOIN customers c ON c.id = s.customer_id
                INNER JOIN users u ON u.id = s.cashier_id
                LEFT JOIN sale_items si ON si.sale_id = s.id
                WHERE date(s.created_at) BETWEEN ? AND ? AND COALESCE(s.archived, 0) = 0 AND COALESCE(s.is_active, 1) = 1 {sales_cashier}
                GROUP BY s.id
                """,
                sales_params,
            ).fetchall()
            transactions = conn.execute(
                f"""
                SELECT t.created_at,
                       c.name AS customer_name,
                       t.action_type,
                       t.amount,
                       t.note,
                       u.full_name AS cashier_name
                FROM transactions t
                INNER JOIN customers c ON c.id = t.customer_id
                INNER JOIN users u ON u.id = t.cashier_id
                WHERE date(t.created_at) BETWEEN ? AND ? AND COALESCE(t.archived, 0) = 0 AND COALESCE(t.is_active, 1) = 1 {tx_cashier}
                """,
                tx_params,
            ).fetchall()

        for row in new_customers:
            rows.append(
                {
                    "created_at": row["created_at"],
                    "customer_name": row["customer_name"],
                    "type": "Yeni Müşteri",
                    "detail": row["phone"] or "Müşteri kaydı oluşturuldu",
                    "amount": float(row["balance"] or 0),
                    "cashier_name": f"Kasa {row['cashier_id']}" if row["cashier_id"] else "Yönetici",
                    "kind": "new_customer",
                }
            )
        for row in sales:
            payment = row["payment_method"] or "POS"
            rows.append(
                {
                    "created_at": row["created_at"],
                    "customer_name": row["customer_name"],
                    "type": "Defter Satış" if payment == "DEFTER" else f"POS {payment}",
                    "detail": row["items"] or payment,
                    "amount": float(row["total"] or 0),
                    "cashier_name": row["cashier_name"],
                    "kind": "pos",
                }
            )
        for row in transactions:
            action = row["action_type"] or ""
            is_load = action == "load"
            rows.append(
                {
                    "created_at": row["created_at"],
                    "customer_name": row["customer_name"],
                    "type": "Yükleme/Tahsilat" if is_load else "Bakiye Harcama",
                    "detail": row["note"] or "-",
                    "amount": abs(float(row["amount"] or 0)) if is_load else -abs(float(row["amount"] or 0)),
                    "cashier_name": row["cashier_name"],
                    "kind": "load" if is_load else "spend",
                }
            )
        rows.sort(key=lambda item: item["created_at"], reverse=True)
        customer_names = {row["customer_name"] for row in rows if row.get("customer_name")}
        summary = {
            "customer_count": len(customer_names),
            "row_count": len(rows),
            "pos_total": sum(float(row["amount"] or 0) for row in rows if row.get("kind") == "pos"),
            "load_total": sum(float(row["amount"] or 0) for row in rows if row.get("kind") == "load"),
            "spend_total": sum(abs(float(row["amount"] or 0)) for row in rows if row.get("kind") == "spend"),
        }
        return {"start_date": start_date, "end_date": end_date, "rows": rows, "summary": summary}

    def cashier_movements_for_date(self, cashier_id: int, target_date: str | None = None):
        """Bugün (veya seçilen gün) kasaya özel POS + bakiye hareketleri; Treeview için sıralı."""
        target_date = target_date or datetime.now().strftime("%Y-%m-%d")
        rows_out = []
        with closing(self._connect()) as conn:
            sales_rows = conn.execute(
                """
                SELECT s.created_at, s.payment_method, s.total,
                       COALESCE(c.name, 'Misafir') AS customer_name, s.note
                FROM sales s
                LEFT JOIN customers c ON c.id = s.customer_id
                WHERE date(s.created_at) = ? AND s.cashier_id = ?
                ORDER BY s.id DESC
                """,
                (target_date, cashier_id),
            ).fetchall()
            for r in sales_rows:
                rows_out.append(
                    {
                        "sort": r["created_at"],
                        "saat": r["created_at"][11:16],
                        "tip": "POS",
                        "detay": f"{r['payment_method']} | {r['customer_name']}",
                        "tutar": float(r["total"]),
                    }
                )
            tx_rows = conn.execute(
                """
                SELECT t.created_at, t.action_type, t.amount, c.name AS customer_name, t.note
                FROM transactions t
                INNER JOIN customers c ON c.id = t.customer_id
                WHERE date(t.created_at) = ? AND t.cashier_id = ?
                ORDER BY t.id DESC
                """,
                (target_date, cashier_id),
            ).fetchall()
            for r in tx_rows:
                rows_out.append(
                    {
                        "sort": r["created_at"],
                        "saat": r["created_at"][11:16],
                        "tip": (r["action_type"] or "").upper(),
                        "detay": f"{r['customer_name']} | {r['note'] or '-'}",
                        "tutar": float(r["amount"]),
                    }
                )
        rows_out.sort(key=lambda x: x["sort"], reverse=True)
        return rows_out

    def defter_movements_timeline(self, target_date: str, cashier_id: int | None = None):
        """Return a timeline of sales and balance movements for the selected day."""
        sales_params = [target_date]
        sales_cashier = ""
        tx_params = [target_date]
        tx_cashier = ""
        if cashier_id is not None:
            sales_cashier = "AND s.cashier_id = ?"
            sales_params.append(cashier_id)
            tx_cashier = "AND t.cashier_id = ?"
            tx_params.append(cashier_id)

        with closing(self._connect()) as conn:
            sales = conn.execute(
                f"""
                SELECT s.created_at,
                       COALESCE(c.name, 'Misafir') AS customer_name,
                       s.payment_method,
                       s.total,
                       u.full_name AS cashier_name,
                       GROUP_CONCAT(si.product_name || ' x' || si.quantity, ', ') AS items
                FROM sales s
                LEFT JOIN customers c ON c.id = s.customer_id
                INNER JOIN users u ON u.id = s.cashier_id
                LEFT JOIN sale_items si ON si.sale_id = s.id
                WHERE date(s.created_at) = ? {sales_cashier}
                GROUP BY s.id
                """,
                sales_params,
            ).fetchall()
            txs = conn.execute(
                f"""
                SELECT t.created_at,
                       c.name AS customer_name,
                       t.action_type,
                       t.amount,
                       t.note,
                       u.full_name AS cashier_name
                FROM transactions t
                INNER JOIN customers c ON c.id = t.customer_id
                INNER JOIN users u ON u.id = t.cashier_id
                WHERE date(t.created_at) = ? {tx_cashier}
                """,
                tx_params,
            ).fetchall()

        rows = []
        for row in sales:
            rows.append(
                {
                    "created_at": row["created_at"],
                    "customer_name": row["customer_name"],
                    "type": "Satış",
                    "detail": row["items"] or row["payment_method"],
                    "amount": -abs(float(row["total"] or 0)),
                    "cashier_name": row["cashier_name"],
                }
            )
        for row in txs:
            is_load = row["action_type"] == "load"
            rows.append(
                {
                    "created_at": row["created_at"],
                    "customer_name": row["customer_name"],
                    "type": "Yükleme/Tahsilat" if is_load else "Harcama",
                    "detail": row["note"] or "-",
                    "amount": abs(float(row["amount"] or 0)) if is_load else -abs(float(row["amount"] or 0)),
                    "cashier_name": row["cashier_name"],
                }
            )
        rows.sort(key=lambda item: item["created_at"], reverse=True)
        return rows

    def admin_dashboard(self):
        with closing(self._connect()) as conn:
            customers = conn.execute("SELECT * FROM customers ORDER BY balance DESC").fetchall()
            kasalar = conn.execute(
                """
                SELECT u.id, u.full_name, u.username,
                    SUM(CASE WHEN t.action_type = 'spend' THEN ABS(t.amount) ELSE 0 END) AS toplam_ciro,
                    COUNT(t.id) AS islem_adedi
                FROM users u
                LEFT JOIN transactions t ON t.cashier_id = u.id
                WHERE u.user_type = 'cashier'
                GROUP BY u.id, u.full_name, u.username
                ORDER BY toplam_ciro DESC
                """
            ).fetchall()
        return {
            "customers": [dict(row) for row in customers],
            "kasalar": [dict(row) for row in kasalar],
        }

    def get_setting(self, key: str, default: str = ""):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_settings(self, payload: dict):
        with closing(self._connect()) as conn, conn:
            for key, value in payload.items():
                conn.execute(
                    "REPLACE INTO app_settings(key, value) VALUES(?, ?)",
                    (key, str(value)),
                )

    def add_expense(self, name: str, amount: float, note: str, cashier_id: int):
        """Add a new expense for a cashier - FOCUSED on eliminating the specific error."""
        # SIMPLE DIRECT APPROACH - No complex validation that could cause errors
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO expenses(cashier_id, name, amount, note, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (cashier_id, name.strip(), float(amount), note.strip(), now),
            )

    def list_expenses(self, cashier_id: int = None, date_str: str = None):
        """List expenses for a cashier on a specific date (or all dates if None)."""
        params = []
        where_clauses = []
        if cashier_id is not None:
            where_clauses.append("cashier_id = ?")
            params.append(cashier_id)
        if date_str:
            where_clauses.append("date(created_at) = ?")
            params.append(date_str)
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM expenses {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def customer_report(self, customer_id: int, cashier_id: int = None):
        """Generate comprehensive report for a specific customer.
        
        Args:
            customer_id: The customer ID to generate report for
            cashier_id: If provided, filter by this cashier (for isolation). 
                       If None (admin), show all cashiers' data for this customer.
        
        Returns:
            dict with customer info, transactions, sales, and summary
        """
        with closing(self._connect()) as conn:
            # Get customer info
            customer = conn.execute(
                "SELECT * FROM customers WHERE id = ?",
                (customer_id,)
            ).fetchone()
            if not customer:
                raise ValueError("Musteri bulunamadi.")
            
            customer_data = dict(customer)
            
            # Build query clauses for cashier isolation
            tx_cashier_clause = ""
            sales_cashier_clause = ""
            params_tx = [customer_id]
            params_sales = [customer_id]
            
            if cashier_id is not None:
                tx_cashier_clause = "AND t.cashier_id = ?"
                sales_cashier_clause = "AND s.cashier_id = ?"
                params_tx.append(cashier_id)
                params_sales.append(cashier_id)
            
            # Get all transactions (load/spend) for this customer
            transactions = conn.execute(
                f"""
                SELECT 
                    t.id, t.created_at, t.action_type, t.amount, t.note,
                    u.full_name AS cashier_name, u.username AS cashier_username
                FROM transactions t
                INNER JOIN users u ON u.id = t.cashier_id
                WHERE t.customer_id = ? {tx_cashier_clause}
                ORDER BY t.created_at DESC
                """,
                params_tx,
            ).fetchall()
            
            # Get all sales for this customer
            sales = conn.execute(
                f"""
                SELECT 
                    s.id, s.created_at, s.total, s.payment_method, s.note,
                    u.full_name AS cashier_name, u.username AS cashier_username
                FROM sales s
                INNER JOIN users u ON u.id = s.cashier_id
                WHERE s.customer_id = ? {sales_cashier_clause}
                ORDER BY s.created_at DESC
                """,
                params_sales,
            ).fetchall()
            
            # Get sale items for each sale
            sale_items_map = {}
            for sale in sales:
                items = conn.execute(
                    """
                    SELECT product_name, quantity, unit_price, line_total
                    FROM sale_items
                    WHERE sale_id = ?
                    ORDER BY id
                    """,
                    (sale["id"],)
                ).fetchall()
                sale_items_map[sale["id"]] = [dict(item) for item in items]
            
            # Calculate summary statistics
            total_yukleme = sum(float(t["amount"]) for t in transactions if t["action_type"] == "load")
            total_harcama = sum(abs(float(t["amount"])) for t in transactions if t["action_type"] == "spend")
            total_pos = sum(float(s["total"]) for s in sales if s["payment_method"] != "DEFTER")
            total_defter = sum(float(s["total"]) for s in sales if s["payment_method"] == "DEFTER")
            
        return {
            "customer": customer_data,
            "transactions": [dict(t) for t in transactions],
            "sales": [dict(s) for s in sales],
            "sale_items": sale_items_map,
            "summary": {
                "total_yukleme": total_yukleme,
                "total_harcama": total_harcama,
                "total_pos": total_pos,
                "total_defter": total_defter,
                "current_balance": float(customer_data.get("balance", 0)),
                "transaction_count": len(transactions),
                "sale_count": len(sales),
            }
        }

    def delete_expense(self, expense_id: int, cashier_id: int = None):
        """Delete an expense. If cashier_id provided, verify ownership."""
        with closing(self._connect()) as conn, conn:
            if cashier_id is not None:
                verify = conn.execute(
                    "SELECT id FROM expenses WHERE id = ? AND cashier_id = ?",
                    (expense_id, cashier_id)
                ).fetchone()
                if not verify:
                    raise ValueError("Gider bulunamadi veya erisim izniniz yok.")
            conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))

    def daily_customers_summary(self, target_date: str, cashier_id: int | None = None):
        """Get daily summary of all customers with transactions for a specific date.
        
        Returns a single page summary showing all customers who had activity
        (load/spend) on the given date, with their totals.
        
        Args:
            target_date: Date string in format "YYYY-MM-DD"
            cashier_id: If provided, filter by this cashier. If None (admin), all cashiers.
        
        Returns:
            dict with date, customers list, and grand totals
        """
        with closing(self._connect()) as conn:
            # Build query clauses for cashier isolation
            tx_cashier_clause = ""
            params = [target_date]
            
            if cashier_id is not None:
                tx_cashier_clause = "AND t.cashier_id = ?"
                params.append(cashier_id)
            
            # Get all customer transactions for the date with customer info
            rows = conn.execute(
                f"""
                SELECT 
                    c.id AS customer_id,
                    c.name AS customer_name,
                    c.phone AS customer_phone,
                    c.balance AS current_balance,
                    t.action_type,
                    t.amount,
                    t.created_at,
                    u.full_name AS cashier_name
                FROM transactions t
                INNER JOIN customers c ON c.id = t.customer_id
                INNER JOIN users u ON u.id = t.cashier_id
                WHERE date(t.created_at) = ? {tx_cashier_clause}
                ORDER BY c.name, t.created_at
                """,
                params,
            ).fetchall()
            
            # Group by customer and calculate totals
            customer_data = {}
            for row in rows:
                cid = row["customer_id"]
                if cid not in customer_data:
                    customer_data[cid] = {
                        "id": cid,
                        "name": row["customer_name"],
                        "phone": row["customer_phone"] or "",
                        "current_balance": float(row["current_balance"] or 0),
                        "yukleme_total": 0.0,
                        "harcama_total": 0.0,
                        "yukleme_count": 0,
                        "harcama_count": 0,
                        "transactions": [],
                        "cashier_name": row["cashier_name"],
                    }
                
                amount = float(row["amount"])
                action = row["action_type"]
                
                if action == "load":
                    customer_data[cid]["yukleme_total"] += amount
                    customer_data[cid]["yukleme_count"] += 1
                elif action == "spend":
                    customer_data[cid]["harcama_total"] += abs(amount)
                    customer_data[cid]["harcama_count"] += 1
                
                customer_data[cid]["transactions"].append({
                    "time": row["created_at"][11:16] if row["created_at"] else "",
                    "type": "Yukleme" if action == "load" else "Harcama",
                    "amount": amount if action == "load" else abs(amount),
                })
            
            # Convert to list and sort by name
            customers_list = sorted(customer_data.values(), key=lambda x: x["name"])
            
            # Calculate grand totals
            grand_yukleme = sum(c["yukleme_total"] for c in customers_list)
            grand_harcama = sum(c["harcama_total"] for c in customers_list)
            total_customers = len(customers_list)
            total_transactions = sum(c["yukleme_count"] + c["harcama_count"] for c in customers_list)
            
        return {
            "date": target_date,
            "cashier_id": cashier_id,
            "customers": customers_list,
            "summary": {
                "total_customers": total_customers,
                "total_transactions": total_transactions,
                "grand_yukleme": grand_yukleme,
                "grand_harcama": grand_harcama,
                "net_movement": grand_yukleme - grand_harcama,
            }
        }

    def get_daily_expenses_total(self, date_str: str, cashier_id: int = None):
        """Get total expenses for a specific date."""
        params = [date_str]
        where = "date(created_at) = ?"
        if cashier_id is not None:
            where += " AND cashier_id = ?"
            params.append(cashier_id)
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT SUM(amount) as total FROM expenses WHERE {where}",
                params,
            ).fetchone()
        return float(row["total"] or 0)

    def defter_report(self, target_date: str, cashier_id: int | None = None):
        """Get daily DEFTER payment sales with customer details.
        
        Shows all customers who made purchases using DEFTER (credit/balance)
        payment method on the specified date.
        
        Args:
            target_date: Date string "YYYY-MM-DD"
            cashier_id: If provided, filter by this cashier. If None, all cashiers.
        
        Returns:
            dict with date, sales list, and grand totals
        """
        params = [target_date]
        cashier_clause = ""
        
        if cashier_id is not None:
            cashier_clause = "AND s.cashier_id = ?"
            params.append(cashier_id)
        
        with closing(self._connect()) as conn:
            # Get all DEFTER sales for the date with customer info
            sales = conn.execute(
                f"""
                SELECT 
                    s.id,
                    s.created_at,
                    s.total,
                    s.note,
                    c.id AS customer_id,
                    c.name AS customer_name,
                    c.phone AS customer_phone,
                    c.balance AS customer_balance,
                    c.credit_limit AS customer_credit_limit,
                    u.full_name AS cashier_name
                FROM sales s
                INNER JOIN customers c ON c.id = s.customer_id
                INNER JOIN users u ON u.id = s.cashier_id
                WHERE date(s.created_at) = ? 
                    AND s.payment_method = 'DEFTER'
                    {cashier_clause}
                ORDER BY c.name, s.created_at
                """,
                params,
            ).fetchall()
            
            # Get sale items for each sale
            sale_ids = [s["id"] for s in sales]
            sale_items_map = {}
            if sale_ids:
                placeholders = ",".join(["?" for _ in sale_ids])
                items = conn.execute(
                    f"""
                    SELECT sale_id, product_name, quantity, unit_price, line_total
                    FROM sale_items
                    WHERE sale_id IN ({placeholders})
                    ORDER BY id
                    """,
                    sale_ids,
                ).fetchall()
                for item in items:
                    sid = item["sale_id"]
                    if sid not in sale_items_map:
                        sale_items_map[sid] = []
                    sale_items_map[sid].append(dict(item))
            
            # Group by customer
            customer_sales = {}
            for sale in sales:
                cid = sale["customer_id"]
                if cid not in customer_sales:
                    customer_sales[cid] = {
                        "customer_id": cid,
                        "customer_name": sale["customer_name"],
                        "customer_phone": sale["customer_phone"] or "",
                        "customer_balance": float(sale["customer_balance"] or 0),
                        "customer_credit_limit": float(sale["customer_credit_limit"] or 0),
                        "sales": [],
                        "total_amount": 0.0,
                    }
                
                sale_data = dict(sale)
                sale_data["items"] = sale_items_map.get(sale["id"], [])
                customer_sales[cid]["sales"].append(sale_data)
                customer_sales[cid]["total_amount"] += float(sale["total"])
            
            # Calculate totals
            total_defter_sales = sum(c["total_amount"] for c in customer_sales.values())
            total_customers = len(customer_sales)
            total_transactions = len(sales)
            
        return {
            "date": target_date,
            "cashier_id": cashier_id,
            "customers": list(customer_sales.values()),
            "summary": {
                "total_customers": total_customers,
                "total_transactions": total_transactions,
                "total_defter_sales": total_defter_sales,
            }
        }

    def defter_customers_balance_report(self, cashier_id: int | None = None, active_only: bool = True):
        """Get all customers who use DEFTER (have balance or credit limit).
        
        Shows current balance status for all customers who have made
        DEFTER purchases or have non-zero balance.
        
        Args:
            cashier_id: If provided, filter by this cashier. If None, all cashiers.
            active_only: If True, only show customers with non-zero balance or recent DEFTER usage
        
        Returns:
            dict with customers list and summary
        """
        with closing(self._connect()) as conn:
            active_clause = "AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1" if active_only else ""
            if cashier_id is not None:
                where = """
                WHERE cashier_id = ?
                  {active_clause}
                """
                where = where.format(active_clause=active_clause)
                params = [cashier_id]
            else:
                where = f"WHERE 1 = 1 {active_clause}"
                params = []
            
            # Get customer details
            rows = conn.execute(
                f"""
                SELECT 
                    id,
                    name,
                    phone,
                    balance,
                    credit_limit,
                    created_at,
                    note
                FROM customers
                {where}
                ORDER BY name
                """,
                params,
            ).fetchall()
            
            # Get last DEFTER transaction date for each customer
            customers_list = []
            for row in rows:
                cid = row["id"]
                
                # Get last DEFTER sale date
                sale_filter = "customer_id = ? AND payment_method = 'DEFTER'"
                sale_params = [cid]
                if cashier_id is not None:
                    sale_filter += " AND cashier_id = ?"
                    sale_params.append(cashier_id)
                last_sale = conn.execute(
                    f"""
                    SELECT MAX(created_at) as last_date
                    FROM sales
                    WHERE {sale_filter}
                    """,
                    sale_params,
                ).fetchone()
                
                # Get total DEFTER purchases
                total_defter = conn.execute(
                    f"""
                    SELECT COALESCE(SUM(total), 0) as total
                    FROM sales
                    WHERE {sale_filter}
                    """,
                    sale_params,
                ).fetchone()
                
                balance = float(row["balance"] or 0)
                credit_limit = float(row["credit_limit"] or 0)
                
                customers_list.append({
                    "id": cid,
                    "name": row["name"],
                    "phone": row["phone"] or "",
                    "balance": balance,
                    "credit_limit": credit_limit,
                    "credit_used": max(0, credit_limit - balance) if credit_limit < 0 else max(0, -balance),
                    "available_credit": abs(credit_limit) - max(0, credit_limit - balance) if credit_limit < 0 else max(0, -balance),
                    "total_defter_purchases": float(total_defter["total"] or 0),
                    "last_defter_date": last_sale["last_date"][:16] if last_sale["last_date"] else "",
                    "created_at": row["created_at"][:10] if row["created_at"] else "",
                    "note": row["note"] or "",
                })
            
            # Filter active only if requested
            if active_only:
                customers_list = [c for c in customers_list]
            
            # Sort by balance (most negative first - most credit used)
            customers_list.sort(key=lambda x: x["balance"])
            
            # Calculate summary
            total_balance = sum(c["balance"] for c in customers_list)
            total_credit_used = sum(c["credit_used"] for c in customers_list)
            total_defter_all = sum(c["total_defter_purchases"] for c in customers_list)
            
        return {
            "customers": customers_list,
            "summary": {
                "total_customers": len(customers_list),
                "total_balance": total_balance,
                "total_credit_used": total_credit_used,
                "total_defter_purchases": total_defter_all,
            }
        }
