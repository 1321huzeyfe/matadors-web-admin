# -*- coding: utf-8 -*-
"""Read-only Supabase web panel for MatadorsApp managers."""

from __future__ import annotations

import json
import mimetypes
import secrets
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from path_utils import resource_path

WEB_ROOT = Path(resource_path("web_panel"))


class WebPanelHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _money(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _today() -> str:
    return datetime.now().date().isoformat()


def _safe_rows(table: str) -> tuple[list[dict], str]:
    try:
        from services.supabase_client import supabase

        response = supabase.table(table).select("*").execute()
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data if isinstance(row, dict)], ""
    except Exception as exc:
        return [], str(exc)


def _branch_value(row: dict) -> str:
    for key in ("branch_id", "profile_id", "kasa_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    cashier_id = row.get("cashier_id")
    return str(cashier_id or "").strip()


def _filter_branch(rows: list[dict], branch: str) -> list[dict]:
    branch = (branch or "").strip()
    if not branch:
        return rows
    return [row for row in rows if _branch_value(row) == branch]


def load_panel_data(branch: str = "") -> dict:
    errors: list[str] = []
    users, err = _safe_rows("users")
    if err:
        errors.append(f"users: {err}")
    customers, err = _safe_rows("customers")
    if err:
        errors.append(f"customers: {err}")
    products, err = _safe_rows("products")
    if err:
        errors.append(f"products: {err}")
    sales, err = _safe_rows("sales")
    if err:
        errors.append(f"sales: {err}")

    active_users = [u for u in users if not bool(u.get("archived")) and u.get("is_active", True) is not False]
    branches = sorted({value for value in (_branch_value(user) for user in active_users) if value})
    customers = _filter_branch(customers, branch)
    products = _filter_branch(products, branch)
    sales = _filter_branch(sales, branch)

    today = _today()
    today_sales = [row for row in sales if str(row.get("created_at") or "").startswith(today)]
    summary_by_branch: dict[str, dict] = {}
    for user in active_users:
        key = _branch_value(user) or str(user.get("username") or user.get("id") or "")
        if not key:
            continue
        summary_by_branch.setdefault(
            key,
            {
                "branch": key,
                "username": user.get("username") or key,
                "role": user.get("role") or user.get("user_type") or "",
                "today_total": 0.0,
                "sale_count": 0,
                "customer_count": 0,
                "product_count": 0,
            },
        )
    for sale in today_sales:
        key = _branch_value(sale)
        if key:
            item = summary_by_branch.setdefault(key, {"branch": key, "username": key, "role": "", "today_total": 0.0, "sale_count": 0, "customer_count": 0, "product_count": 0})
            item["today_total"] += _money(sale.get("total"))
            item["sale_count"] += 1
    for customer in customers:
        key = _branch_value(customer)
        if key in summary_by_branch:
            summary_by_branch[key]["customer_count"] += 1
    for product in products:
        key = _branch_value(product)
        if key in summary_by_branch:
            summary_by_branch[key]["product_count"] += 1

    balances = sorted(
        [
            {
                "name": row.get("name") or row.get("customer_name") or "-",
                "balance": _money(row.get("balance")),
                "branch": _branch_value(row),
            }
            for row in customers
        ],
        key=lambda item: str(item["name"]).casefold(),
    )
    stock = sorted(
        [
            {
                "name": row.get("name") or row.get("product_name") or "-",
                "stock": _money(row.get("stock")),
                "price": _money(row.get("price")),
                "branch": _branch_value(row),
            }
            for row in products
        ],
        key=lambda item: str(item["name"]).casefold(),
    )

    return {
        "ok": not errors,
        "errors": errors,
        "branch": branch,
        "branches": branches,
        "summary": {
            "today_total": sum(_money(row.get("total")) for row in today_sales),
            "sale_count": len(today_sales),
            "customer_count": len(customers),
            "product_count": len(products),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "by_branch": sorted(summary_by_branch.values(), key=lambda item: item["branch"]),
        "sales": sorted(today_sales, key=lambda row: str(row.get("created_at") or ""), reverse=True)[:100],
        "balances": balances[:200],
        "stock": stock[:200],
    }


class PanelHandler(BaseHTTPRequestHandler):
    panel_password = ""
    panel_token = ""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            return self._send_login()
        if parsed.path == "/logout":
            return self._send_logout()
        if parsed.path == "/styles.css":
            return self._send_static(parsed.path)
        if parsed.path == "/app.js":
            return self._send_static(parsed.path)
        if not self._is_authorized():
            return self._send_unauthorized(is_api=parsed.path.startswith("/api/"))
        if parsed.path == "/api/panel":
            branch = parse_qs(parsed.query).get("branch", [""])[0]
            return self._send_json(load_panel_data(branch))
        return self._send_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            return self._handle_login()
        self.send_error(405, "Read-only panel")

    def do_PUT(self):
        self.send_error(405, "Read-only panel")

    def do_DELETE(self):
        self.send_error(405, "Read-only panel")

    def _is_authorized(self) -> bool:
        cookie = self.headers.get("Cookie", "")
        return bool(self.panel_password and self.panel_token and f"matadors_panel={self.panel_token}" in cookie)

    def _handle_login(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(min(length, 2048)).decode("utf-8", errors="replace")
        password = parse_qs(raw).get("password", [""])[0]
        if secrets.compare_digest(password, self.panel_password):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"matadors_panel={self.panel_token}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            return
        self._send_login(error="Şifre hatalı.")

    def _send_login(self, error: str = "") -> None:
        error_html = f'<p class="error">{error}</p>' if error else ""
        body = f"""<!doctype html>
<html lang="tr">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>MatadorsApp Web Panel</title><link rel="stylesheet" href="/styles.css"></head>
<body class="login-page"><form class="login-card" method="post" action="/login"><p class="eyebrow">MatadorsApp</p><h1>Yönetici Paneli</h1><input name="password" type="password" placeholder="Panel şifresi" autocomplete="current-password" autofocus>{error_html}<button type="submit">Giriş Yap</button></form></body>
</html>""".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_logout(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", "matadors_panel=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()

    def _send_unauthorized(self, is_api: bool = False) -> None:
        if is_api:
            return self._send_json({"ok": False, "errors": ["Yetkisiz erişim."]}, status=401)
        self.send_response(303)
        self.send_header("Location", "/login")
        self.end_headers()

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, request_path: str) -> None:
        relative = request_path.strip("/") or "index.html"
        target = (WEB_ROOT / relative).resolve()
        if not target.is_relative_to(WEB_ROOT) or not target.exists() or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix.lower() in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def create_server(host: str = "127.0.0.1", port: int = 8765, password: str = "") -> ThreadingHTTPServer:
    if not password:
        raise ValueError("Web panel şifresi zorunlu.")
    token = secrets.token_urlsafe(32)

    class AuthenticatedPanelHandler(PanelHandler):
        panel_password = password
        panel_token = token

    return WebPanelHTTPServer((host, port), AuthenticatedPanelHandler)


def run(host: str = "127.0.0.1", port: int = 8765, password: str = "admin123") -> None:
    server = create_server(host, port, password)
    print(f"Web panel started on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run()
