# -*- coding: utf-8 -*-
import os
import string
import locale
import json
from collections import defaultdict
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk, simpledialog, colorchooser, filedialog

# CRITICAL: Import CustomTkinter FIRST and make it globally available
import customtkinter as ctk
from path_utils import get_kasa_reports_dir, get_reports_dir
from services.pdf_fonts import get_pdf_fonts
from performance import measure
from ui.shortcuts import bind_ctrl_shortcut, bind_enter_action
from ui.styles import BLACK_BUTTON, BLACK_BUTTON_HOVER, BUTTON_SIZE_PRESETS, MATADORS_THEME, SIDEBAR_MUTED, SIDEBAR_TEXT
from db.auth import InactiveUserError
CTK_AVAILABLE = True

# ENSURE ctk is available globally for ALL modules
globals()['ctk'] = ctk

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError as e:
    print(f"Cryptography import error: {e}")
    CRYPTO_AVAILABLE = False

try:
    from tkcalendar import DateEntry
    CALENDAR_AVAILABLE = True
except ImportError as e:
    print(f"TkCalendar import error: {e}")
    CALENDAR_AVAILABLE = False

# Configure Turkish locale for this module with error handling
try:
    locale.setlocale(locale.LC_ALL, 'Turkish_Turkey.1254')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'tr_TR.UTF-8')
    except locale.Error:
        pass  # Use default if Turkish locale not available
except Exception as e:
    print(f"Locale configuration warning: {e}")
    pass  # Continue with default locale



# Default Matadors theme with customizable regions
DEFAULT_NEON_THEME = MATADORS_THEME.copy()

# Theme presets
THEME_PRESETS = {
    "custom": DEFAULT_NEON_THEME.copy(),
}

CARD_COLORS = ["#E30613", "#111111", "#FFFFFF", "#F9FAFB"]


from services.pdf_reports import money, write_report_pdf

def _entry_kwargs(t):
    return {
        "fg_color": t["input"],
        "border_color": t["border"],
        "text_color": t["text"],
    }


def _style_glass_toplevel(window, t, opacity=0.95):
    """Apply the current dialog styling."""
    window.configure(fg_color=t.get("panel", t["bg"]))
    try:
        window.wm_attributes("-alpha", float(t.get("dialog_opacity", opacity)))
    except Exception:
        pass


def _cashier_is_active(cashier: dict) -> bool:
    return not bool(cashier.get("archived")) and cashier.get("is_active", 1) not in (0, False)


def _run_ui_background(widget, app, name: str, work, on_success, error_title: str = "Hata"):
    def safe_work():
        try:
            return True, work()
        except Exception as exc:
            return False, str(exc)

    def finish(result):
        ok, payload = result
        if ok:
            on_success(payload)
        else:
            messagebox.showerror(error_title, str(payload), parent=widget)

    if hasattr(app, "run_background_io"):
        app.run_background_io(name, safe_work, finish, lambda exc: messagebox.showerror(error_title, str(exc), parent=widget))
    else:
        finish(safe_work())

def _apply_vip_background(frame, app):
    """VIP arka plan resmini frame'e yerleştirir."""
    bg_path = app.get_vip_background_image()
    if bg_path:
        try:
            from PIL import Image
            img = Image.open(bg_path)
            ctk_bg = ctk.CTkImage(light_image=img, dark_image=img, size=(2560, 1440))
            bg_label = ctk.CTkLabel(frame, text="", image=ctk_bg)
            bg_label.place(relx=0, rely=0, relwidth=1, relheight=1)
            # Resmin en altta kalmasını sağla
            bg_label.lower()
        except Exception:
            pass

def load_brand_logo(app, size=(52, 52)):
    """Kulüp logosu; PIL yoksa veya dosya yoksa None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    asset_root = getattr(app, "assets_dir", os.path.join(app.base_dir, "assets"))
    for name in ("logo.png", "app_icon.png", "club_logo.jpg"):
        path = os.path.join(asset_root, name)
        if os.path.isfile(path):
            try:
                img = Image.open(path).convert("RGBA")
                img.thumbnail(size, Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", size, (0, 0, 0, 0))
                canvas.alpha_composite(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
                img = canvas
                return ctk.CTkImage(light_image=img, dark_image=img, size=size)
            except Exception:
                continue
    return None


class LoginFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        t = app.theme
        super().__init__(parent, fg_color=t["bg"])
        self.app = app
        self.pack(fill="both", expand=True)
        
        _apply_vip_background(self, app)

        box = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=24, border_width=2, border_color=t["accent"])
        box.place(relx=0.5, rely=0.5, anchor="center")

        logo = load_brand_logo(app, size=(72, 72))
        if logo:
            ctk.CTkLabel(box, text="", image=logo).pack(pady=(28, 8))

        ctk.CTkLabel(box, text="Matadors Club", font=ctk.CTkFont(size=28, weight="bold"), text_color=t["text"]).pack(padx=48, pady=(8, 8))
        ctk.CTkLabel(box, text="Kasa girişi", font=ctk.CTkFont(size=14), text_color=t["muted"]).pack(pady=(0, 20))

        self.username = ctk.CTkEntry(box, width=300, placeholder_text="Kullanıcı adı", **_entry_kwargs(t))
        self.username.pack(padx=32, pady=6)
        self.password = ctk.CTkEntry(box, width=300, placeholder_text="Şifre", show="*", **_entry_kwargs(t))
        self.password.pack(padx=32, pady=6)

        ctk.CTkButton(
            box,
            text="Giriş Yap",
            width=300,
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            text_color="white",
            command=self.login,
        ).pack(padx=32, pady=20)
        bind_enter_action(self, self.login, "Giriş")

    def login(self):
        try:
            user = self.app.db.authenticate(self.username.get(), self.password.get())
        except InactiveUserError:
            messagebox.showerror("Hata", "Bu kasa pasif. Yönetici ile iletişime geçin.")
            return
        if not user:
            messagebox.showerror("Hata", "Kullanıcı adı veya şifre hatalı.")
            return
        if user.get("user_type") != "admin" and not self.app.is_setup_complete():
            messagebox.showwarning(
                "Kurulum",
                "Bu bilgisayarda kurulum tamamlanmadı.\n\nÖnce yönetici girişi yapıp Drive klasörünü seçmelidir.",
            )
            return
        self.app.load_user_panel(user)


class MainShell(ctk.CTkFrame):
    @measure("dashboard_render_suresi", lambda self, parent, app, user: f"MainShell user={user.get('username') if isinstance(user, dict) else ''}")
    def __init__(self, parent, app, user: dict):
        t = app.theme
        super().__init__(parent, fg_color=t["bg"])
        self.app = app
        self.user = user
        self.is_admin = user["user_type"] == "admin"
        self.db = app.get_cashier_db(user.get("username")) if not self.is_admin else app.db
        self.pack(fill="both", expand=True)

        self.nav_buttons = {}
        self.shell = ctk.CTkFrame(self, fg_color=t["bg"], corner_radius=0)
        self.shell.pack(fill="both", expand=True)
        self.sidebar = ctk.CTkFrame(self.shell, fg_color=t["sidebar"], width=224, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.main_area = ctk.CTkFrame(self.shell, fg_color=t["bg"], corner_radius=0)
        self.main_area.pack(side="left", fill="both", expand=True)

        self._build_top_bar()

        self.page_container = ctk.CTkFrame(self.main_area, fg_color=t["bg"])
        self.page_container.pack(fill="both", expand=True, padx=0, pady=(0, 10))

        self.pages: dict = {}
        if self.is_admin:
            self.pages["settings"] = AdminSettingsPage(self.page_container, app, user, db=self.db)
        else:
            self.pages["home"] = HomePage(self.page_container, app, user, db=self.db)
            self.pages["ledger"] = LedgerPage(self.page_container, app, user, db=self.db)
            self.pages["settings"] = CashierSettingsPage(self.page_container, app, user, db=self.db)

        for page in self.pages.values():
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.active_page_key = None
        self._bind_shell_shortcuts()
        self.show_page("settings" if self.is_admin else "home")

    def _build_top_bar(self):
        t = self.app.theme
        side_text = SIDEBAR_TEXT
        side_muted = SIDEBAR_MUTED

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 22))
        img = load_brand_logo(self.app, size=(86, 86))
        if img:
            ctk.CTkLabel(brand, text="", image=img).pack(pady=(0, 12))
        ctk.CTkLabel(
            brand,
            text=self.app.db.get_setting("app_title", "Matadors Club"),
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=side_text,
        ).pack()
        ctk.CTkLabel(brand, text="POS Sistemi", font=ctk.CTkFont(size=12), text_color=side_muted).pack(pady=(3, 0))

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.pack(fill="x", padx=14, pady=(8, 0))

        top = ctk.CTkFrame(self.main_area, fg_color=t["top"], height=72, corner_radius=0)
        top.pack(fill="x")
        top.pack_propagate(False)
        self.page_title = ctk.CTkLabel(top, text="", font=ctk.CTkFont(size=19, weight="bold"), text_color=t["text"])
        self.page_title.pack(side="left", padx=24)

        ctk.CTkButton(
            top,
            text="Çıkış",
            width=86,
            height=36,
            fg_color=t["danger"],
            hover_color="#991b1b",
            command=self.app.show_login,
        ).pack(side="right", padx=(8, 20))

        ctk.CTkLabel(
            top,
            text=f"{self.user['full_name'][:22]}",
            text_color=t["muted"],
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="right", padx=8)

        def nav_btn(key, label):
            btn = ctk.CTkButton(
                nav,
                text=label,
                width=188,
                height=44,
                fg_color="transparent",
                text_color=side_muted,
                hover_color="#181818",
                font=ctk.CTkFont(size=14, weight="bold"),
                anchor="w",
                corner_radius=10,
                command=lambda k=key: self.show_page(k),
            )
            btn.pack(fill="x", pady=4)
            self.nav_buttons[key] = btn

        if self.is_admin:
            nav_btn("settings", "AYARLAR")
        else:
            nav_btn("home", "ANA EKRAN")
            nav_btn("ledger", "DEFTER")
            nav_btn("settings", "AYARLAR")

        ctk.CTkLabel(
            self.sidebar,
            text="Hızlı satış ve müşteri takibi",
            text_color=side_muted,
            font=ctk.CTkFont(size=11),
            wraplength=170,
            justify="center",
        ).pack(side="bottom", padx=14, pady=(0, 22))

    def open_theme_customizer(self):
        ThemeCustomizerDialog(self, self.app)

    def _highlight_nav(self, key: str):
        t = self.app.theme
        for k, btn in self.nav_buttons.items():
            if k == key:
                btn.configure(fg_color=t["accent"], text_color="white", hover_color=t["accent_hover"])
            else:
                btn.configure(fg_color="transparent", text_color="#D1D5DB", hover_color="#181818")
        titles = {"home": "ANA EKRAN", "ledger": "DEFTER", "settings": "AYARLAR"}
        if hasattr(self, "page_title"):
            self.page_title.configure(text=titles.get(key, "MATADORS CLUB"))

    @measure("dashboard_render_suresi", lambda self, key: f"show_page={key}")
    def show_page(self, key: str):
        if key not in self.pages:
            return
        self.active_page_key = key
        self._highlight_nav(key)
        self.pages[key].tkraise()
        if hasattr(self.pages[key], "on_show"):
            self.pages[key].on_show()

    def _bind_shell_shortcuts(self):
        self.app._active_shell = self
        top = self.winfo_toplevel()

        def run_customer(event):
            if getattr(self.app, "_active_shell", None) is not self:
                return None
            if event.widget.winfo_toplevel() is not top:
                return None
            self._shortcut_new_customer()
            return "break"

        def run_product(event):
            if getattr(self.app, "_active_shell", None) is not self:
                return None
            if event.widget.winfo_toplevel() is not top:
                return None
            self._shortcut_new_product()
            return "break"

        def run_control_key(event):
            if getattr(self.app, "_active_shell", None) is not self:
                return None
            if event.widget.winfo_toplevel() is not top:
                return None
            if not (event.state & 0x0004):
                return None
            key = (event.keysym or "").lower()
            char = event.char or ""
            if key == "m" or char == "\r":
                self._shortcut_new_customer()
                return "break"
            if key == "u" or char == "\x15":
                self._shortcut_new_product()
                return "break"
            return None

        top.bind_all("<Control-m>", run_customer, add="+")
        top.bind_all("<Control-M>", run_customer, add="+")
        top.bind_all("<Control-KeyPress-m>", run_customer, add="+")
        top.bind_all("<Control-KeyPress-M>", run_customer, add="+")
        top.bind_all("<Control-u>", run_product, add="+")
        top.bind_all("<Control-U>", run_product, add="+")
        top.bind_all("<Control-KeyPress-u>", run_product, add="+")
        top.bind_all("<Control-KeyPress-U>", run_product, add="+")
        top.bind_all("<KeyPress>", run_control_key, add="+")

    def _shortcut_new_customer(self):
        if self.active_page_key != "ledger":
            return
        page = self.pages.get("ledger")
        if page and hasattr(page, "_new_customer"):
            page._new_customer()

    def _shortcut_new_product(self):
        if self.active_page_key != "home":
            return
        page = self.pages.get("home")
        if page and hasattr(page, "_new_product_shortcut"):
            page._new_product_shortcut()


class HomePage(ctk.CTkFrame):
    @measure("dashboard_render_suresi", lambda self, parent, app, user, db=None: f"HomePage user={user.get('username') if isinstance(user, dict) else ''}")
    def __init__(self, parent, app, user: dict, db=None):
        t = app.theme
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.user = user
        self.db = db or app.db  # Use provided db or fallback to app.db
        self.is_admin = user.get("user_type") == "admin"
        self.cart = defaultdict(lambda: {"quantity": 0})
        self._products_dirty = True
        self._categories_dirty = True
        self._last_products_key = None
        self._refreshing_products = False
        self._pending_product_refresh = False
        self._product_stock_labels = {}
        self._sale_in_progress = False
        saved_cart_width = int(self.app.db.get_setting("cart_panel_width", "420") or 420)
        self.cart_width = ctk.IntVar(value=max(280, min(760, saved_cart_width)))
        self.category_var = ctk.StringVar(value="Tüm Ürünler")
        self.status_var = ctk.StringVar(value="Hızlı satış ekranı hazır")

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 8))

        self.cat = ctk.CTkComboBox(
            top,
            values=["Tüm Ürünler"],
            variable=self.category_var,
            width=200,
            command=lambda _v: self.schedule_product_refresh(80),
            **_entry_kwargs(t),
        )
        self.cat.pack(side="left")

        ctk.CTkLabel(
            top,
            textvariable=self.status_var,
            fg_color="#1e293b",
            corner_radius=8,
            text_color=t["text"],
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left", fill="x", expand=True, padx=16, ipady=10, ipadx=16)

        # Product settings button for cashier
        ctk.CTkButton(
            top,
            text="Ürün Ayarları",
            fg_color=t["panel2"],
            hover_color=t["accent"],
            command=self._open_product_settings,
        ).pack(side="right", padx=(0, 10))

        # Other expenses button
        ctk.CTkButton(
            top,
            text="Diğer Giderler",
            fg_color=t["danger"],
            hover_color="#991b1b",
            command=self._open_expenses_dialog,
        ).pack(side="right", padx=(0, 10))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1, minsize=420)
        body.grid_columnconfigure(1, weight=0, minsize=280)

        self.products_panel = ctk.CTkFrame(body, fg_color="transparent")
        self.products_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.products_panel.grid_rowconfigure(0, weight=1)
        self.products_panel.grid_columnconfigure(0, weight=1)

        self.grid_frame = ctk.CTkScrollableFrame(self.products_panel, fg_color="transparent", orientation="vertical")
        self.grid_frame.grid(row=0, column=0, sticky="nsew")
        self._last_product_columns = 0
        self._resize_refresh_job = None
        self.products_panel.bind("<Configure>", self._on_products_resize)

        self.cart_panel = ctk.CTkFrame(body, fg_color=t["panel"], corner_radius=16, border_width=1, border_color=t["border"], width=self.cart_width.get())
        self.cart_panel.grid(row=0, column=1, sticky="nsew")
        self.cart_panel.pack_propagate(False)
        self.cart_panel.grid_propagate(False)

        # Header
        header_frame = ctk.CTkFrame(self.cart_panel, fg_color="transparent")
        header_frame.pack(fill="x", padx=18, pady=(18, 10))
        
        ctk.CTkLabel(header_frame, text="Sepetim", font=ctk.CTkFont(size=22, weight="bold"), text_color=t["text"]).pack(side="left")

        # Scrollable frame for cart items (clickable)
        self.cart_scroll = ctk.CTkScrollableFrame(self.cart_panel, height=280, fg_color=t["input"], border_color=t["border"], border_width=1, corner_radius=12)
        self.cart_scroll.pack(fill="both", expand=True, padx=18, pady=6)
        self.selected_cart_item = None  # Track selected item

        pay = ctk.CTkFrame(self.cart_panel, fg_color=t["panel2"], corner_radius=12)
        pay.pack(fill="x", padx=18, pady=10)
        for col in range(3):
            pay.grid_columnconfigure(col, weight=1, uniform="pay")
        ctk.CTkButton(pay, text="Nakit Öde", width=90, height=44, fg_color=BLACK_BUTTON, hover_color=BLACK_BUTTON_HOVER, command=self._cash).grid(row=0, column=0, sticky="ew", padx=5, pady=8)
        ctk.CTkButton(
            pay,
            text="Kart ile Öde",
            width=90,
            height=44,
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            command=self._card_payment,
        ).grid(row=0, column=1, sticky="ew", padx=5, pady=8)
        ctk.CTkButton(pay, text="Defter", width=90, height=44, fg_color=BLACK_BUTTON, hover_color=BLACK_BUTTON_HOVER, command=self._defter).grid(row=0, column=2, sticky="ew", padx=5, pady=8)

        self.total_lbl = ctk.CTkLabel(self.cart_panel, text="Toplam: 0,00 TL", font=ctk.CTkFont(size=20, weight="bold"), text_color=t["text"])
        self.total_lbl.pack(anchor="e", padx=18, pady=10)

        ctk.CTkButton(
            self.cart_panel,
            text="Seçili ürünü azalt",
            fg_color=t["danger"],
            hover_color="#991b1b",
            command=self._dec_selected,
        ).pack(fill="x", padx=18, pady=4)
        ctk.CTkButton(self.cart_panel, text="Sepeti Boşalt", fg_color=t["panel2"], command=self._clear).pack(fill="x", padx=14, pady=(4, 16))

    @measure("dashboard_render_suresi", lambda self: "HomePage.on_show")
    def on_show(self):
        try:
            cashier_id = self.user["id"] if not self.is_admin else None
            if self._categories_dirty:
                cats = self.db.get_product_categories(cashier_id=cashier_id)
                self.cat.configure(values=cats)
                if self.category_var.get() not in cats:
                    self.category_var.set("Tüm Ürünler")
                self._categories_dirty = False
            if self._products_dirty:
                self.refresh_products()
            self._refresh_cart_ui()
        except Exception as exc:
            print(f"HomePage on_show skipped: {exc}")

    def _visible_items(self):
        return [x for x in self.cart.values() if x.get("quantity", 0) > 0]

    def _total(self):
        return sum(x["quantity"] * x["price"] for x in self._visible_items())

    @measure("urun_arama_suresi", lambda self: f"category={self.category_var.get() if hasattr(self, 'category_var') else ''}")
    def refresh_products(self):
        if self._refreshing_products:
            self._pending_product_refresh = True
            return
        self._refreshing_products = True
        t = self.app.theme
        try:
            for w in self.grid_frame.winfo_children():
                w.destroy()
            self._product_stock_labels = {}

            cashier_id = self.user["id"] if not self.is_admin else None
            category = self.category_var.get()
            products = self.db.list_products(category, cashier_id=cashier_id)
            self._last_products_key = (category, cashier_id)
            self._products_dirty = False

            columns = self._product_columns()
            self._last_product_columns = columns
            for i in range(6):
                self.grid_frame.columnconfigure(i, weight=0)
            for i in range(int(columns)):
                self.grid_frame.columnconfigure(i, weight=1, uniform="product_card")

            if not products:
                empty = ctk.CTkFrame(self.grid_frame, fg_color=t["panel"], corner_radius=14, border_width=1, border_color=t["border"])
                empty.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
                ctk.CTkLabel(empty, text="Ürün bulunamadı", text_color=t["muted"], font=ctk.CTkFont(size=14)).pack(padx=18, pady=18)
                return

            for i, p in enumerate(products):
                icon = p.get("icon", "") or self._get_product_icon(p["name"], p["category"])
                is_featured = i == 0
                card = ctk.CTkFrame(
                    self.grid_frame,
                    fg_color=t["card"],
                    corner_radius=14,
                    width=190,
                    height=152,
                    border_width=2 if is_featured else 1,
                    border_color=t["accent"] if is_featured else t["border"],
                )
                card.grid(row=i // columns, column=i % columns, padx=10, pady=10, sticky="nsew")
                card.grid_propagate(False)
                card.bind("<Button-1>", lambda _e, pr=p: self._add(pr))
                card.bind("<Enter>", lambda _e, c=card, featured=is_featured: self._set_product_hover(c, True, featured))
                card.bind("<Leave>", lambda _e, c=card, featured=is_featured: self._set_product_hover(c, False, featured))

                content = ctk.CTkFrame(card, fg_color="transparent")
                content.pack(fill="both", expand=True, padx=14, pady=12)
                content.bind("<Button-1>", lambda _e, pr=p: self._add(pr))

                top_row = ctk.CTkFrame(content, fg_color="transparent")
                top_row.pack(fill="x")
                icon_lbl = ctk.CTkLabel(top_row, text=icon, font=ctk.CTkFont(size=30), text_color=t["text"])
                icon_lbl.pack(side="left")
                icon_lbl.bind("<Button-1>", lambda _e, pr=p: self._add(pr))
                stock_lbl = ctk.CTkLabel(
                    top_row,
                    text=f"Stok {int(p['stock'])}",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=t["muted"],
                    fg_color=t["panel2"],
                    corner_radius=8,
                )
                stock_lbl.pack(side="right", ipadx=8, ipady=3)
                stock_lbl.bind("<Button-1>", lambda _e, pr=p: self._add(pr))
                self._product_stock_labels[int(p["id"])] = stock_lbl

                name = p['name'][:30] + "..." if len(p['name']) > 30 else p['name']
                name_lbl = ctk.CTkLabel(content, text=name, font=ctk.CTkFont(size=14, weight="bold"), text_color=t["text"], anchor="w", justify="left", wraplength=150)
                name_lbl.pack(fill="x", pady=(10, 2))
                name_lbl.bind("<Button-1>", lambda _e, pr=p: self._add(pr))
                cat_lbl = ctk.CTkLabel(content, text=p.get("category", ""), font=ctk.CTkFont(size=11), text_color=t["muted"], anchor="w")
                cat_lbl.pack(fill="x")
                cat_lbl.bind("<Button-1>", lambda _e, pr=p: self._add(pr))

                bottom = ctk.CTkFrame(content, fg_color="transparent")
                bottom.pack(fill="x", side="bottom")
                price_lbl = ctk.CTkLabel(bottom, text=money(p['price']), font=ctk.CTkFont(size=14, weight="bold"), text_color=t["accent"])
                price_lbl.pack(side="left")
                price_lbl.bind("<Button-1>", lambda _e, pr=p: self._add(pr))
                for child in (content, top_row, icon_lbl, stock_lbl, name_lbl, cat_lbl, bottom, price_lbl):
                    child.bind("<Enter>", lambda _e, c=card, featured=is_featured: self._set_product_hover(c, True, featured))
                    child.bind("<Leave>", lambda _e, c=card, featured=is_featured: self._set_product_hover(c, False, featured))
        except Exception as exc:
            print(f"Product refresh failed: {exc}")
        finally:
            self._refreshing_products = False
            if self._pending_product_refresh:
                self._pending_product_refresh = False
                self.schedule_product_refresh(120)

    def schedule_product_refresh(self, delay_ms: int = 180):
        self._products_dirty = True
        if self._resize_refresh_job:
            try:
                self.after_cancel(self._resize_refresh_job)
            except Exception:
                pass
        self._resize_refresh_job = self.after(delay_ms, self.refresh_products)

    def _set_product_hover(self, card, active: bool, featured: bool = False):
        t = self.app.theme
        if active:
            card.configure(border_color=t["accent"], border_width=2, fg_color="#FFF5F5")
        else:
            card.configure(
                border_color=t["accent"] if featured else t["border"],
                border_width=2 if featured else 1,
                fg_color=t["card"],
            )

    def _product_columns(self) -> int:
        available_width = max(360, self.products_panel.winfo_width() or self.grid_frame.winfo_width() or 720)
        return int(max(2, min(4, available_width // 210)))

    def _on_products_resize(self, _event=None):
        columns = self._product_columns()
        if columns == getattr(self, "_last_product_columns", 0):
            return
        if self._resize_refresh_job:
            try:
                self.after_cancel(self._resize_refresh_job)
            except Exception:
                pass
        self._resize_refresh_job = self.after(180, self.refresh_products)

    def _get_product_icon(self, name: str, category: str) -> str:
        """Return emoji icon based on product name or category."""
        name_lower = name.lower()
        cat_lower = category.lower()
        
        # Drinks
        if any(x in name_lower for x in ["su", "soda", "water"]):
            return "💧"
        if any(x in name_lower for x in ["kahve", "coffee", "americano", "filtre", "espresso"]):
            return "☕"
        if any(x in name_lower for x in ["cay", "tea"]):
            return "🍵"
        if any(x in name_lower for x in ["smoothie", "milkshake", "icecek", "drink"]):
            return "🥤"
        
        # Supplements / Fitness
        if any(x in name_lower for x in ["protein", "whey"]):
            return "💪"
        if any(x in name_lower for x in ["pre-workout", "preworkout", "pre workout"]):
            return "⚡"
        if any(x in name_lower for x in ["bcaa", "amino", "eaa"]):
            return "🧬"
        if any(x in name_lower for x in ["creatine", "kreatin"]):
            return "🏋️"
        if any(x in name_lower for x in ["carnitine", "karnitin", "shot"]):
            return "🔥"
        if any(x in name_lower for x in ["vitamin", "multivitamin"]):
            return "💊"
        if any(x in name_lower for x in ["omega", "fish oil", "balik yagi"]):
            return "🐟"
        
        # Snacks / Food
        if any(x in name_lower for x in ["bar", "protein bar", "snack"]):
            return "🍫"
        if any(x in name_lower for x in ["meyve", "fruit"]):
            return "🍎"
        if any(x in name_lower for x in ["yogurt", "yoğurt"]):
            return "🥛"
        if any(x in name_lower for x in ["kuruyemis", "nuts", "fistik", "findik", "ceviz"]):
            return "🥜"
        if any(x in name_lower for x in ["sandwich", "sandviç", "tost", "wrap"]):
            return "🥪"
        if any(x in name_lower for x in ["salata", "salad"]):
            return "🥗"
        
        # Category-based fallback
        if "su" in cat_lower or "icecek" in cat_lower or "drink" in cat_lower:
            return "🥤"
        if "kahve" in cat_lower or "coffee" in cat_lower:
            return "☕"
        if "takviye" in cat_lower or "supplement" in cat_lower or "fitness" in cat_lower:
            return "💊"
        if "bar" in cat_lower or "snack" in cat_lower:
            return "🍫"
        if "yiyecek" in cat_lower or "food" in cat_lower:
            return "🍽️"
        
        return "🛍️"

    def _lighten_color(self, hex_color: str, percent: int) -> str:
        """Lighten a hex color by given percentage."""
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        factor = 1 + (percent / 100)
        r = min(255, int(r * factor))
        g = min(255, int(g * factor))
        b = min(255, int(b * factor))
        
        return f"#{r:02x}{g:02x}{b:02x}"

    @measure("sepet_guncelleme_suresi", lambda self, product: f"add product_id={product.get('id') if isinstance(product, dict) else ''}")
    def _add(self, product: dict):
        row = self.cart[product["id"]]
        row.update({"product_id": product["id"], "name": product["name"], "price": product["price"]})
        row["quantity"] += 1
        self.status_var.set(f"{product['name']} sepete eklendi")
        self._refresh_cart_ui()

    @measure("sepet_guncelleme_suresi", lambda self: f"items={len(self._visible_items()) if hasattr(self, 'cart') else 0}")
    def _refresh_cart_ui(self):
        for widget in self.cart_scroll.winfo_children():
            widget.destroy()

        t = self.app.theme
        items = self._visible_items()

        if not items:
            empty = ctk.CTkFrame(self.cart_scroll, fg_color="transparent")
            empty.pack(fill="both", expand=True, padx=10, pady=28)
            ctk.CTkLabel(
                empty,
                text="Sepet",
                text_color=t["muted"],
                font=ctk.CTkFont(size=34),
            ).pack(pady=(8, 4))
            ctk.CTkLabel(
                empty,
                text="Sepet boş",
                text_color=t["muted"],
                font=ctk.CTkFont(size=15, weight="bold"),
            ).pack()
            self.total_lbl.configure(text="Toplam: 0,00 TL")
            return

        total = 0.0
        for item in sorted(items, key=lambda x: x["product_id"]):
            lt = item["quantity"] * item["price"]
            total += lt
            is_selected = self.selected_cart_item == item["product_id"]
            row = ctk.CTkFrame(
                self.cart_scroll,
                fg_color=t["accent"] if is_selected else t["panel2"],
                corner_radius=10,
                border_width=1,
                border_color=t["accent"] if is_selected else t["border"],
            )
            row.pack(fill="x", padx=4, pady=4)
            row.bind("<Button-1>", lambda _e, pid=item["product_id"]: self._select_cart_item(pid))

            qty = ctk.CTkLabel(
                row,
                text=f"x{item['quantity']}",
                width=36,
                text_color="white" if is_selected else t["text"],
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            qty.pack(side="left", padx=(10, 8), pady=10)
            qty.bind("<Button-1>", lambda _e, pid=item["product_id"]: self._select_cart_item(pid))

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, pady=8)
            info.bind("<Button-1>", lambda _e, pid=item["product_id"]: self._select_cart_item(pid))
            name = item["name"][:28] + "..." if len(item["name"]) > 28 else item["name"]
            name_lbl = ctk.CTkLabel(
                info,
                text=name,
                anchor="w",
                text_color="white" if is_selected else t["text"],
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            name_lbl.pack(fill="x")
            name_lbl.bind("<Button-1>", lambda _e, pid=item["product_id"]: self._select_cart_item(pid))
            unit_lbl = ctk.CTkLabel(
                info,
                text=f"Birim: {money(item['price'])}",
                anchor="w",
                text_color="#FEE2E2" if is_selected else t["muted"],
                font=ctk.CTkFont(size=11),
            )
            unit_lbl.pack(fill="x")
            unit_lbl.bind("<Button-1>", lambda _e, pid=item["product_id"]: self._select_cart_item(pid))

            price = ctk.CTkLabel(
                row,
                text=money(lt),
                width=92,
                text_color="white" if is_selected else t["accent"],
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            price.pack(side="right", padx=(8, 10), pady=10)
            price.bind("<Button-1>", lambda _e, pid=item["product_id"]: self._select_cart_item(pid))

        self.total_lbl.configure(text=f"Toplam: {money(total)}")

    def _resize_cart_panel(self, value, save=True):
        width = max(280, min(760, int(float(value))))
        self.cart_width.set(width)
        self.cart_panel.configure(width=width)
        try:
            total_width = self.sales_panes.winfo_width()
            if total_width > width + 360:
                self.sales_panes.sash_place(0, total_width - width, 0)
        except Exception:
            pass
        if save:
            self.app.db.set_settings({"cart_panel_width": width})

    def _sync_cart_width_from_sash(self):
        try:
            total_width = self.sales_panes.winfo_width()
            sash_x = self.sales_panes.sash_coord(0)[0]
            width = max(280, min(760, total_width - sash_x))
            self.cart_width.set(width)
            self.cart_panel.configure(width=width)
            self.app.db.set_settings({"cart_panel_width": width})
        except Exception as e:
            print(f"[HomePage] cart width sync skipped: {e}")

    def _select_cart_item(self, product_id: int):
        """Select a cart item for decrease operation."""
        if self.selected_cart_item == product_id:
            self.selected_cart_item = None  # Deselect if already selected
        else:
            self.selected_cart_item = product_id
        self._refresh_cart_ui()

    @measure("sepet_guncelleme_suresi", lambda self: "dec_selected")
    def _dec_selected(self):
        """Decrease quantity of selected item."""
        if self.selected_cart_item is None:
            messagebox.showwarning("Seçim", "Lütfen azaltmak istediğiniz ürünü sepetten seçin.")
            return
        
        item = self.cart.get(self.selected_cart_item)
        if not item or item["quantity"] <= 0:
            return
        
        item["quantity"] -= 1
        
        if item["quantity"] <= 0:
            self.cart.pop(self.selected_cart_item, None)
            self.selected_cart_item = None
        
        self._refresh_cart_ui()

    def _scroll_products(self, direction):
        """Scroll products horizontally with mouse wheel."""
        # Get the canvas widget from the scrollable frame
        canvas = self.grid_frame._parent_canvas
        if canvas:
            current_x = canvas.xview()[0]  # Get current scroll position
            canvas_width = canvas.winfo_width()
            content_width = canvas.bbox("all")[2] if canvas.bbox("all") else canvas_width
            
            # Calculate scroll amount (10% of visible area)
            scroll_amount = 0.1
            if direction == "right":
                new_x = min(1.0, current_x + scroll_amount)
            else:
                new_x = max(0.0, current_x - scroll_amount)
            
            canvas.xview_moveto(new_x)

    @measure("sepet_guncelleme_suresi", lambda self: "clear")
    def _clear(self):
        self.cart = defaultdict(lambda: {"quantity": 0})
        self.selected_cart_item = None
        self._refresh_cart_ui()

    def _cash(self):
        if not self._visible_items():
            messagebox.showwarning("Sepet", "Sepet boş.")
            return
        CashPayDialog(self, self.app.theme, self._total(), lambda: self._finalize("NAKIT"))

    def _card_payment(self):
        if not self._visible_items():
            messagebox.showwarning("Sepet", "Sepet boş.")
            return
        PayConfirmDialog(self, self.app.theme, "Kart", self._total(), lambda: self._finalize("KART"))

    def _defter(self):
        if not self._visible_items():
            messagebox.showwarning("Sepet", "Sepet boş.")
            return
        DefterPickerDialog(self, self.app, self._complete_defter, user=self.user)

    def _complete_defter(self, customer: dict):
        total = self._total()
        predicted = customer["balance"] - total
        force = False
        if predicted < customer["credit_limit"]:
            force = messagebox.askyesno(
                "Limit",
                f"{customer['name']} için yeni bakiye {money(predicted)} olacak.\nDevam edilsin mi?",
            )
            if not force:
                return
        self._finalize("DEFTER", customer, force)

    @measure("satis_kayit_suresi", lambda self, method, customer=None, force_limit=False: f"ui_finalize method={method} items={len(self._visible_items()) if hasattr(self, 'cart') else 0}")
    def _finalize(self, method: str, customer: dict | None = None, force_limit: bool = False):
        if self._sale_in_progress:
            return
        self._sale_in_progress = True
        self.status_var.set("Satış kaydediliyor...")
        try:
            sale_id, total, rem = self.db.create_sale(
                customer["id"] if customer else None,
                self._visible_items(),
                method,
                self.user["id"],
                note=method,
                force_limit=force_limit,
            )
        except ValueError as e:
            if str(e) == "LIMIT_CONFIRM_REQUIRED" and customer:
                if messagebox.askyesno("Onay", "Limit aşılıyor. Devam edilsin mi?"):
                    self._sale_in_progress = False
                    return self._finalize(method, customer, True)
                self._sale_in_progress = False
                return
            messagebox.showerror("Hata", str(e))
            self._sale_in_progress = False
            return
        except Exception as exc:
            messagebox.showerror("Hata", str(exc))
            self._sale_in_progress = False
            return

        # Clear cart immediately after successful payment
        sold_items = list(self._visible_items())
        self._clear()
        self._apply_sold_stock_delta(sold_items)
        
        # Show success message
        self.status_var.set(f"Satış #{sale_id} tamamlandı — {money(total)}")
        def sale_housekeeping():
            self.app.backup_manager.create_backup(reason="sale_completed")
            self.app.export_cashier_files(self.user.get("username"))

        if hasattr(self.app, "run_background_io"):
            self.app.run_background_io("sale_housekeeping", sale_housekeeping)
        else:
            try:
                sale_housekeeping()
            except Exception as e:
                print(f"Sale backup error: {e}")
        
        # Show remaining balance for defter payments
        if customer and rem is not None:
            messagebox.showinfo("Defter", f"Kalan bakiye: {money(rem)}")
        self._sale_in_progress = False

    def _apply_sold_stock_delta(self, sold_items: list[dict]):
        """Update visible stock labels without rebuilding the whole product grid."""
        for item in sold_items:
            try:
                product_id = int(item.get("product_id") or 0)
                label = self._product_stock_labels.get(product_id)
                if not label:
                    continue
                current = str(label.cget("text") or "")
                current_stock = int(float(current.replace("Stok", "").strip() or 0))
                next_stock = max(0, current_stock - int(float(item.get("quantity", 0) or 0)))
                label.configure(text=f"Stok {next_stock}")
            except Exception as exc:
                print(f"Stock label update skipped: {exc}")

    def _open_product_settings(self):
        """Open product management for cashier users."""
        ProductManageDialog(self.winfo_toplevel(), self.app, user=self.user, db=self.db, on_change=self._mark_products_dirty)

    def _new_product_shortcut(self):
        """Open the new product form directly from the sales screen."""
        ProductEditDialog(self.winfo_toplevel(), self.app, None, self._save_new_product_shortcut)

    def _save_new_product_shortcut(self, data: dict):
        cashier_id = None if self.user.get("user_type") == "admin" else self.user.get("id")
        self.db.add_product(
            data["name"],
            data["category"],
            data["price"],
            data["stock"],
            data.get("icon", ""),
            cashier_id=cashier_id,
        )
        if self.user.get("user_type") != "admin" and hasattr(self.app, "run_background_io"):
            username = self.user.get("username")
            self.app.run_background_io("product_export", lambda: self.app.export_cashier_files(username))
        self._mark_products_dirty()
        self.refresh_products()
        messagebox.showinfo("Ürün", "Ürün kaydedildi.")

    def _mark_products_dirty(self):
        self._products_dirty = True
        self._categories_dirty = True

    def _open_expenses_dialog(self):
        """Open expenses dialog for adding other expenses."""
        ExpenseDialog(self.winfo_toplevel(), self.app, user=self.user)


class LedgerPage(ctk.CTkFrame):
    @measure("dashboard_render_suresi", lambda self, parent, app, user, db=None: f"LedgerPage user={user.get('username') if isinstance(user, dict) else ''}")
    def __init__(self, parent, app, user: dict, db=None):
        t = app.theme
        super().__init__(parent, fg_color=t["bg"])
        self.app = app
        self.user = user
        self.db = db or app.db
        self.is_admin = user["user_type"] == "admin"
        self.admin_cashiers = self.app.list_kasa_sources() if self.is_admin else []
        self.admin_cashier_by_label = {
            f"{row['full_name']} (@{row['username']})": row for row in self.admin_cashiers
        }
        self.admin_selected_cashier = None
        self._rendering_cards = False
        self._pending_render_cards = False

        head = ctk.CTkFrame(self, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
        head.pack(fill="x", padx=20, pady=(16, 8))
        info = ctk.CTkFrame(head, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=16, pady=12)
        self.summary = ctk.CTkLabel(info, text="", font=ctk.CTkFont(size=16, weight="bold"), text_color=t["text"], anchor="w")
        self.summary.pack(fill="x", anchor="w")
        self.activity_summary = ctk.CTkLabel(info, text="", font=ctk.CTkFont(size=13), text_color=t["muted"], anchor="w")
        self.activity_summary.pack(fill="x", anchor="w", pady=(4, 0))
        ctk.CTkButton(head, text="Müşteri İşlem Kaydı", fg_color=t["accent"], hover_color=t["accent_hover"], command=self._pdf_today).pack(side="right", padx=(8, 16), pady=8)
        ctk.CTkButton(head, text="Müşteri Bakiye Durumu", fg_color=t["panel2"], text_color=t["text"], hover_color=t["border"], command=self._open_customer_balance_status).pack(side="right", padx=(8, 0), pady=8)

        row = ctk.CTkFrame(self, fg_color=t["bg"])
        row.pack(fill="x", padx=20, pady=6)
        self.search = ctk.CTkEntry(row, placeholder_text="Müşteri ara...", width=360, **_entry_kwargs(t))
        self.search.pack(side="left", padx=(0, 12))
        self._search_after_id = None
        self.search.bind("<KeyRelease>", lambda _e: self._schedule_render_cards())
        ctk.CTkButton(row, text="Yeni Müşteri", fg_color=t["accent"], hover_color=t["accent_hover"], command=self._new_customer).pack(side="left", padx=4)
        self.show_archived = ctk.BooleanVar(value=False)
        if self.is_admin:
            labels = list(self.admin_cashier_by_label.keys())
            if labels:
                self.admin_selected_label = ctk.StringVar(value=labels[0])
                self.admin_selected_cashier = self.admin_cashier_by_label[labels[0]]
                self.db = self.app.get_cashier_db(self.admin_selected_cashier["username"])
                ctk.CTkComboBox(
                    row,
                    values=labels,
                    variable=self.admin_selected_label,
                    width=260,
                    command=self._select_admin_cashier,
                    **_entry_kwargs(t),
                ).pack(side="left", padx=(0, 12))
            ctk.CTkCheckBox(
                row,
                text="Arşivlenmiş kayıtları göster",
                variable=self.show_archived,
                command=self.render_cards,
                text_color=t["muted"],
            ).pack(side="left", padx=12)

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=t["bg"])
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.after_idle(self.on_show)

    def _select_admin_cashier(self, label: str):
        self.admin_selected_cashier = self.admin_cashier_by_label.get(label)
        if self.admin_selected_cashier:
            self.db = self.app.get_cashier_db(self.admin_selected_cashier["username"])
        self.on_show()

    def _active_cashier_context(self):
        if self.is_admin:
            if not self.admin_selected_cashier:
                return None, None
            return self.admin_selected_cashier.get("id"), self.admin_selected_cashier.get("username")
        return self.user["id"], self.user.get("username")

    def _write_current_cashier_files(self):
        _, username = self._active_cashier_context()
        if username:
            def work():
                self.app.export_cashier_files(username)

            if hasattr(self.app, "run_background_io"):
                self.app.run_background_io("cashier_json_export", work)
            else:
                try:
                    work()
                except Exception as exc:
                    print(f"Kasa JSON yazma hatası: {exc}")

    def _schedule_render_cards(self):
        if self._search_after_id:
            try:
                self.after_cancel(self._search_after_id)
            except Exception:
                pass
        self._search_after_id = self.after(180, self.render_cards)

    @measure("dashboard_render_suresi", lambda self: "LedgerPage.on_show")
    def on_show(self):
        self._refresh_summary()
        self.render_cards()

    def _refresh_summary(self):
        today = datetime.now().strftime("%Y-%m-%d")
        cashier_id, username = self._active_cashier_context()
        if self.is_admin:
            if not cashier_id:
                self.summary.configure(text="Kasa seçilmedi.")
                self.activity_summary.configure(text="")
                return
            r = self.db.daily_report(today, cashier_id=cashier_id)
            self.summary.configure(text=f"Bugün ({username}) - POS: {money(r['pos_total'])} | Bakiye harcama: {money(r['ciro'])} | Yüklenme: {money(r['yukleme'])}")
        else:
            r = self.db.daily_report(today, cashier_id=cashier_id)
            self.summary.configure(text=f"Bugün - POS: {money(r['pos_total'])} | Bakiye harcama: {money(r['ciro'])} | İşlem: {r['islem_sayisi']}")
        activity = self.db.customer_activity_between(today, today, cashier_id=cashier_id)
        s = activity["summary"]
        self.activity_summary.configure(
            text=f"Bugün işlem yapan müşteriler: {s['customer_count']} kişi | Kayıt: {s['row_count']} | POS: {money(s['pos_total'])} | Yükleme: {money(s['load_total'])}"
        )

    def _pdf_today(self):
        cashier_id, _username = self._active_cashier_context()

        def work():
            outputs = self.app.create_customer_activity_archives(datetime.now().strftime("%Y-%m-%d"), cashier_id)
            return outputs[0]

        def done(daily):
            messagebox.showinfo(
                "Müşteri İşlem Kaydı",
                "Günlük, haftalık ve aylık müşteri işlem PDF raporları oluşturuldu.\n\n"
                f"Günlük PDF:\n{daily['pdf']}"
                "\nPDF klasörü: Masaüstü/MatadorsApp_Raporlar",
                parent=self,
            )

        _run_ui_background(self, self.app, "customer_activity_pdf", work, done, "Hata")

    def _open_customer_balance_status(self):
        cashier_id, username = self._active_cashier_context()
        if self.is_admin and not username:
            messagebox.showwarning("Müşteri Bakiye Durumu", "Önce bir kasa seçin.")
            return
        CustomerBalanceStatusDialog(self, self.app, self.db, cashier_id, username)

    @measure("dashboard_render_suresi", lambda self: "LedgerPage.render_cards")
    def render_cards(self):
        if self._rendering_cards:
            self._pending_render_cards = True
            return
        self._rendering_cards = True
        t = self.app.theme
        try:
            for w in self.scroll.winfo_children():
                w.destroy()
            cashier_id, username = self._active_cashier_context()
            if self.is_admin and not username:
                empty = ctk.CTkFrame(self.scroll, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
                empty.pack(fill="x", pady=8)
                ctk.CTkLabel(empty, text="Önce bir kasa seçin", text_color=t["muted"], font=ctk.CTkFont(size=14)).pack(padx=18, pady=18)
                return
            include_archived = bool(self.is_admin and self.show_archived.get())
            customers = self.db.list_customers(self.search.get(), cashier_id=cashier_id, include_archived=include_archived)
            if not customers:
                empty = ctk.CTkFrame(self.scroll, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
                empty.pack(fill="x", pady=8)
                ctk.CTkLabel(empty, text="Müşteri bulunamadı", text_color=t["muted"], font=ctk.CTkFont(size=14)).pack(padx=18, pady=18)
                return
            for c in customers:
                balance = float(c.get("balance", 0))
                limit = float(c.get("credit_limit", 0))
                status_color = t["success"] if balance >= 0 and balance >= limit else t["danger"]
                card = ctk.CTkFrame(self.scroll, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
                card.pack(fill="x", pady=7)
                left = ctk.CTkFrame(card, fg_color="transparent")
                left.pack(side="left", fill="both", expand=True, padx=14, pady=12)
                ctk.CTkFrame(left, fg_color=status_color, width=4, corner_radius=2).pack(side="left", fill="y", padx=(0, 12))
                av = ctk.CTkLabel(left, text=(c.get("avatar") or c["name"][:2]).upper()[:2], width=48, height=48, fg_color="#111111", text_color="#FFFFFF", corner_radius=24, font=ctk.CTkFont(size=18, weight="bold"))
                av.pack(side="left", padx=(0, 12))
                txt = ctk.CTkFrame(left, fg_color="transparent")
                txt.pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(txt, text=c["name"], font=ctk.CTkFont(size=17, weight="bold"), text_color=t["text"]).pack(anchor="w")
                ctk.CTkLabel(txt, text=f"Bakiye: {money(balance)} | Limit: {money(limit)}", text_color=status_color, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
                ctk.CTkLabel(txt, text=c.get("note") or c.get("phone") or "", text_color=t["muted"], font=ctk.CTkFont(size=12)).pack(anchor="w")
                btns = ctk.CTkFrame(card, fg_color="transparent")
                btns.pack(side="right", padx=12, pady=12)
                ctk.CTkButton(btns, text="Düzenle", width=96, fg_color=t["panel2"], text_color=t["text"], command=lambda row=c: self._edit(row)).pack(side="left", padx=4)
                ctk.CTkButton(btns, text="Bakiye", width=96, fg_color=t["accent"], hover_color=t["accent_hover"], command=lambda row=c: self._set_bal(row)).pack(side="left", padx=4)
                ctk.CTkButton(btns, text="Hareket", width=96, fg_color="#111111", hover_color="#2b2b2b", command=lambda row=c: self._hist(row)).pack(side="left", padx=4)
                if self.is_admin:
                    ctk.CTkButton(btns, text="Sil", width=70, fg_color=t["danger"], command=lambda row=c: self._delete(row)).pack(side="left", padx=4)
        except Exception as exc:
            print(f"Ledger render failed: {exc}")
        finally:
            self._rendering_cards = False
            if self._pending_render_cards:
                self._pending_render_cards = False
                self._schedule_render_cards()

    def _new_customer(self):
        CustomerFormDialog(self, self.app, None, self._save_new, user=self._target_user())

    def _target_user(self):
        if self.is_admin and self.admin_selected_cashier:
            row = dict(self.admin_selected_cashier)
            row["user_type"] = "cashier"
            return row
        return self.user

    def _save_new(self, data: dict):
        similar = self.app.find_similar_customer_by_phone(data.get("phone", ""))
        if similar and not messagebox.askyesno("Benzer müşteri var", "Bu telefon numarasıyla benzer müşteri var. Yine de kaydedilsin mi?"):
            return
        self.app.create_customer_for_user(self._target_user(), data)
        self._write_current_cashier_files()
        self.on_show()

    def _edit(self, c: dict):
        CustomerFormDialog(self, self.app, c, lambda d: self._save_edit(c["id"], d), on_delete=lambda row=c: self._delete(row), user=self.user)

    def _save_edit(self, cid: int, d: dict):
        cashier_id, _username = self._active_cashier_context()
        self.db.update_customer(cid, d["name"], d["phone"], d.get("avatar", ""), float(d["credit_limit"]), d.get("note", ""), cashier_id=cashier_id)
        old = self.db.get_customer(cid, cashier_id=cashier_id)
        if old and abs(float(old["balance"]) - float(d.get("balance", 0))) > 0.001:
            try:
                self.db.set_balance(cid, float(d["balance"]), cashier_id=cashier_id)
            except Exception as e:
                messagebox.showerror("Hata", str(e))
                return
        self._write_current_cashier_files()
        self.on_show()

    def _set_bal(self, c: dict):
        value = simpledialog.askfloat("Bakiye", "Yeni bakiye", initialvalue=float(c["balance"]), parent=self)
        if value is None:
            return
        cashier_id, _username = self._active_cashier_context()
        try:
            self.db.set_balance(c["id"], value, cashier_id=cashier_id)
            self._write_current_cashier_files()
            self.on_show()
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _hist(self, c: dict):
        cashier_id, _username = self._active_cashier_context()
        h = self.db.recent_balance_history(c["id"], cashier_id=cashier_id)
        win = ctk.CTkToplevel(self)
        win.title("Hareketler")
        win.geometry("720x420")
        _style_glass_toplevel(win, self.app.theme)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        tb = ctk.CTkTextbox(win, fg_color=self.app.theme["input"], text_color=self.app.theme["text"])
        tb.pack(fill="both", expand=True, padx=16, pady=16)
        if not h:
            tb.insert("end", "Hareket bulunamadı.\n")
        for r in h:
            tb.insert("end", f"{r['created_at'][:16]} | {r['action_type']} | {money(r['amount'])} | {r['note']}\n")

    def _delete(self, c: dict):
        cashier_id, _username = self._active_cashier_context()
        customer_password = self.app.db.get_setting("customer_operation_password", "1234")
        pwd = simpledialog.askstring("Güvenlik", "Müşteri işlem şifresini girin:", show="*", parent=self)
        if pwd != customer_password:
            messagebox.showerror("Hata", "Şifre yanlış!")
            return
        if messagebox.askyesno("Sil", "Müşteri silinsin mi?"):
            self.db.delete_customer(c["id"], cashier_id=cashier_id)
            self._write_current_cashier_files()
            self.on_show()


class CashierSettingsPage(ctk.CTkFrame):
    """Limited settings page for cashier users."""

    @measure("dashboard_render_suresi", lambda self, parent, app, user, db=None: f"CashierSettingsPage user={user.get('username') if isinstance(user, dict) else ''}")
    def __init__(self, parent, app, user: dict, db=None):
        t = app.theme
        super().__init__(parent, fg_color=t["bg"])
        self.app = app
        self.user = user
        self.db = db or app.db
        wrapper = ctk.CTkFrame(self, fg_color="transparent")
        wrapper.pack(fill="both", expand=True, padx=28, pady=24)
        ctk.CTkLabel(wrapper, text="Kasa Ayarları", font=ctk.CTkFont(size=28, weight="bold"), text_color=t["text"]).pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(wrapper, text="Bu alan kasa kullanıcısının günlük işlemleri için gerekli ayarları içerir.", font=ctk.CTkFont(size=14), text_color=t["muted"]).pack(anchor="w", pady=(0, 18))
        grid = ctk.CTkFrame(wrapper, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="settings")
        self._card(grid, 0, 0, "Görünüm", "Uygulamanın renklerini, panel görünümünü ve pencere ayarlarını düzenle.", "Görünüm Ayarları", lambda: ThemeCustomizerDialog(self, self.app))
        self._card(grid, 0, 1, "Ürünler", "Bu kasaya ait ürün listesi yönetici tarafından kasa kartından güncellenir.", "Ürünleri Gör", lambda: ProductManageDialog(self.winfo_toplevel(), self.app, user=self.user, on_change=None))
        self._card(grid, 1, 0, "Şifre", "Bu kasanın giriş şifresini değiştir.", "Şifre Değiştir", lambda: AdminPasswordDialog(self, self.app, cashier_username=self.user["username"]))
        self._card(grid, 1, 1, "Günlük Rapor", "Bugünün kasa raporunu tek tıkla PDF olarak al.", "PDF Al", self._pdf_today)
        self._card(grid, 2, 0, "Müşteriler", "Sadece bu kasaya ait müşterileri, bakiyeleri ve hareketleri yönet.", "Müşteri Ayarları", self._open_customer_settings)
        self._card(grid, 2, 1, "Giderler", "Günlük diğer giderleri bu kasaya ait olarak kaydet.", "Gider Ekle", lambda: ExpenseDialog(self.winfo_toplevel(), self.app, user=self.user))

    def _card(self, parent, row, col, title, body, button_text, command):
        t = self.app.theme
        card = ctk.CTkFrame(parent, fg_color=t.get("glass", t["panel"]), corner_radius=14, border_width=1, border_color=t["border"])
        card.grid(row=row, column=col, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=18, weight="bold"), text_color=t["text"]).pack(anchor="w", padx=18, pady=(18, 6))
        ctk.CTkLabel(card, text=body, font=ctk.CTkFont(size=13), text_color=t["muted"], justify="left", wraplength=420).pack(anchor="w", padx=18, pady=(0, 16))
        ctk.CTkButton(card, text=button_text, fg_color=t["accent"], hover_color=t["accent_hover"], command=command).pack(anchor="w", padx=18, pady=(0, 18))

    def _pdf_today(self):
        def work():
            return self.app.create_report_pdf(datetime.now().strftime("%Y-%m-%d"), self.user["id"])

        def done(path):
            messagebox.showinfo("Rapor", f"PDF oluşturuldu:\n{path}", parent=self)

        _run_ui_background(self, self.app, "cashier_daily_pdf", work, done, "Hata")

    def _open_customer_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Müşteri Ayarları")
        win.geometry("1180x760")
        win.minsize(980, 640)
        _style_glass_toplevel(win, self.app.theme)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        LedgerPage(win, self.app, self.user, db=self.db).pack(fill="both", expand=True)


class CashierDetailDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, cashier: dict, on_saved):
        super().__init__(parent)
        self.app = app
        self.parent_page = parent
        self.db = app.db
        self.cashier = cashier
        self.cashier_id = cashier["id"]
        self.cashier_username = cashier.get("username", "")
        self.cashier_active = _cashier_is_active(cashier)
        self.cashier_db = app.get_cashier_db(self.cashier_username)
        self.on_saved = on_saved
        t = app.theme
        self.title(f"Kasa: {cashier['full_name']}")
        self.geometry("1120x760")
        self.minsize(980, 640)
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        tabs = ctk.CTkTabview(self, fg_color=t["panel"], segmented_button_selected_color=t["accent"], segmented_button_selected_hover_color=t["accent_hover"], text_color=t["text"])
        tabs.pack(fill="both", expand=True, padx=16, pady=16)
        info = tabs.add("Bilgiler")
        today = tabs.add("Bugün")
        reports = tabs.add("Raporlar")
        customers = tabs.add("Müşteriler")
        products = tabs.add("Ürünler")
        self._build_info(info)
        self._build_today(today)
        self._build_reports(reports)
        self._build_customers(customers)
        self._build_products(products)

    def _build_info(self, parent):
        t = self.app.theme
        ctk.CTkLabel(parent, text="Kasa bilgileri", font=ctk.CTkFont(size=18, weight="bold"), text_color=t["text"]).pack(anchor="w", padx=18, pady=(18, 8))
        status_text = "Durum: Aktif" if self.cashier_active else "Durum: Pasif"
        status_color = t["success"] if self.cashier_active else t["danger"]
        ctk.CTkLabel(parent, text=status_text, text_color=status_color, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=18, pady=(0, 8))
        self.e_name = ctk.CTkEntry(parent, width=360, **_entry_kwargs(t)); self.e_name.pack(anchor="w", padx=18, pady=6); self.e_name.insert(0, self.cashier.get("full_name", ""))
        self.e_user = ctk.CTkEntry(parent, width=360, **_entry_kwargs(t)); self.e_user.pack(anchor="w", padx=18, pady=6); self.e_user.insert(0, self.cashier.get("username", ""))
        self.e_pass = ctk.CTkEntry(parent, width=360, placeholder_text="Yeni Şifre", show="*", **_entry_kwargs(t)); self.e_pass.pack(anchor="w", padx=18, pady=6)
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(anchor="w", padx=18, pady=14)
        ctk.CTkButton(actions, text="Kaydet", fg_color=t["accent"], command=self._save_info).pack(side="left")
        if self.cashier_active:
            ctk.CTkButton(
                actions,
                text="Pasifleştir",
                fg_color=t["danger"],
                hover_color="#991b1b",
                command=self._passivate_cashier,
            ).pack(side="left", padx=(10, 0))
        else:
            ctk.CTkButton(
                actions,
                text="Aktif Et",
                fg_color=t["success"],
                hover_color=t.get("success_hover", t["success"]),
                command=self._activate_cashier,
            ).pack(side="left", padx=(10, 0))

    def _build_today(self, parent):
        t = self.app.theme
        tree = ttk.Treeview(parent, columns=("saat", "tip", "detay", "tutar"), show="headings", height=18)
        for col, title, w in [("saat", "Saat", 70), ("tip", "Tip", 110), ("detay", "Açıklama", 520), ("tutar", "Tutar", 120)]:
            tree.heading(col, text=title); tree.column(col, width=w)
        tree.pack(fill="both", expand=True, padx=18, pady=18)
        rows = self.cashier_db.cashier_movements_for_date(self.cashier_id, datetime.now().strftime("%Y-%m-%d"))
        if not rows:
            tree.insert("", "end", values=("--", "Bilgi", "Bugün işlem bulunamadı", money(0)))
        for row in rows:
            tree.insert("", "end", values=(row["saat"], row["tip"], row["detay"], money(row["tutar"])))

    def _build_reports(self, parent):
        t = self.app.theme
        box = ctk.CTkTextbox(parent, fg_color=t["input"], text_color=t["text"])
        box.pack(fill="both", expand=True, padx=18, pady=18)
        r = self.cashier_db.daily_report(datetime.now().strftime("%Y-%m-%d"), cashier_id=self.cashier_id)
        box.insert("end", f"Bugün - POS: {money(r['pos_total'])} | Bakiye harcama: {money(r['ciro'])} | İşlem: {r['islem_sayisi']}\n")

    def _build_customers(self, parent):
        cashier_user = {
            "id": self.cashier_id,
            "username": self.cashier.get("username", ""),
            "user_type": "cashier",
            "full_name": self.cashier.get("full_name", ""),
        }
        LedgerPage(parent, self.app, cashier_user, db=self.app.get_cashier_db(cashier_user["username"])).pack(fill="both", expand=True)

    def _build_products(self, parent):
        admin_user = {"id": self.app.current_user.get("id", 1), "user_type": "admin", "username": "admin"}
        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.pack(fill="x", padx=16, pady=(14, 0))
        t = self.app.theme
        ctk.CTkButton(
            wrapper,
            text="Stok Düzenleme",
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            command=lambda: StockAdjustmentDialog(
                self,
                self.app,
                db=self.cashier_db,
                cashier_id=self.cashier_id,
                username=self.cashier_username,
            ),
        ).pack(side="left")
        ProductManageDialog(
            parent,
            self.app,
            user=admin_user,
            embedded=True,
            db=self.cashier_db,
            manage_cashier_id=self.cashier_id,
            manage_username=self.cashier_username,
            on_change=self.on_saved,
        )

    def _save_info(self):
        try:
            updated = self.app.update_cashier_profile(
                self.cashier_id,
                self.e_user.get(),
                self.e_name.get(),
                self.e_pass.get().strip(),
            )
        except Exception as e:
            messagebox.showerror("Hata", str(e)); return
        self.cashier = updated
        self.cashier_username = updated.get("username", "")
        self.cashier_db = self.app.get_cashier_db(self.cashier_username)
        self.title(f"Kasa: {updated.get('full_name', self.cashier_username)}")
        self.e_user.delete(0, "end")
        self.e_user.insert(0, updated.get("username", ""))
        self.e_name.delete(0, "end")
        self.e_name.insert(0, updated.get("full_name", ""))
        self.e_pass.delete(0, "end")
        self.on_saved()
        messagebox.showinfo("Kasa", "Kasa güncellendi.")

    def _passivate_cashier(self):
        if not messagebox.askyesno(
            "Pasifleştir",
            f"@{self.cashier_username} kasası pasifleştirilsin mi?\n\nVeriler silinmeyecek, local DB ve Supabase kayıtları korunacak.",
            parent=self,
        ):
            return
        self._run_active_toggle(False)

    def _activate_cashier(self):
        if not messagebox.askyesno(
            "Aktif Et",
            f"@{self.cashier_username} kasası aktif edilsin mi?",
            parent=self,
        ):
            return
        self._run_active_toggle(True)

    def _run_active_toggle(self, active: bool):
        def work():
            if active:
                return self.app.activate_cashier_profile(self.cashier_id)
            return self.app.passivate_cashier_profile(self.cashier_id)

        def done(updated):
            if hasattr(self.parent_page, "_apply_cashier_active_result"):
                self.parent_page._apply_cashier_active_result(self.cashier, updated)
            else:
                self.on_saved()
            messagebox.showinfo("Kasa", "Kasa aktif edildi." if active else "Kasa pasifleştirildi.", parent=self)
            self.destroy()

        def failed(exc):
            messagebox.showerror("Hata", str(exc), parent=self)

        self.app.run_background_io("cashier_detail_active_toggle", work, done, failed)


class CashierCreateDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, on_created):
        super().__init__(parent)
        self.app = app; self.on_created = on_created; t = app.theme
        self.title("Yeni Kasa"); self.geometry("420x300"); _style_glass_toplevel(self, t); self.transient(parent.winfo_toplevel()); self.grab_set()
        self.e_user = ctk.CTkEntry(self, placeholder_text="Kullanıcı adı", width=320, **_entry_kwargs(t)); self.e_user.pack(padx=20, pady=(24, 8))
        self.e_name = ctk.CTkEntry(self, placeholder_text="Kasa adı", width=320, **_entry_kwargs(t)); self.e_name.pack(padx=20, pady=8)
        self.e_pass = ctk.CTkEntry(self, placeholder_text="Şifre", show="*", width=320, **_entry_kwargs(t)); self.e_pass.pack(padx=20, pady=8)
        ctk.CTkButton(self, text="Oluştur", fg_color=t["accent"], command=self._ok).pack(pady=18)
    def _ok(self):
        try:
            self.app.create_cashier_profile(self.e_user.get(), self.e_name.get(), self.e_pass.get())
        except Exception as e:
            messagebox.showerror("Hata", str(e)); return
        self.on_created(); self.destroy()


class CloudSettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; t = app.theme
        self.title("Bulut Ayarları"); self.geometry("680x500"); self.minsize(600, 440); _style_glass_toplevel(self, t); self.transient(parent.winfo_toplevel()); self.grab_set()
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=22)
        ctk.CTkLabel(
            body,
            text="Google Drive sistemi pasif",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=t["text"],
        ).pack(anchor="w", pady=(0, 10))
        ctk.CTkLabel(
            body,
            text="Canlı senkron Supabase üzerinden çalışır. İnternet yoksa işlemler yerel SQLite'a yazılır ve kuyruk internet geldiğinde gönderilir.",
            text_color=t["muted"],
            wraplength=600,
            justify="left",
        ).pack(anchor="w")
        ctk.CTkButton(body, text="Kapat", fg_color=t["accent"], hover_color=t["accent_hover"], command=self.destroy).pack(anchor="e", pady=(28, 0))


class WebPanelDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, user: dict):
        super().__init__(parent)
        self.app = app
        self.user = user
        t = app.theme
        self.title("Web Paneli")
        self.geometry("560x260")
        self.minsize(500, 300)
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=24, pady=22)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body,
            text="Yönetici Web Paneli",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=t["text"],
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ctk.CTkLabel(
            body,
            text="Yerel 127.0.0.1/port paneli pasif. Yönetici paneli masaüstü uygulamadan bağımsız olarak web_admin_panel klasöründen internete yayınlanır ve Supabase verilerini sadece okur.",
            text_color=t["muted"],
            wraplength=500,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 18))
        ctk.CTkButton(body, text="Kapat", fg_color=t["accent"], hover_color=t["accent_hover"], command=self.destroy).grid(row=2, column=0, sticky="e")

class BackupSettingsDialog(ctk.CTkToplevel):
    """Local backup controls."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.manager = app.backup_manager
        self.security = app.security_manager
        self.title("Veri Güvenliği / Yedekleme")
        self.geometry("760x620")
        t = app.theme
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 10))
        ctk.CTkLabel(
            header,
            text="Veri Güvenliği / Yedekleme",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=t["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Yedekler aylık klasörlerde saklanır. Arşiv kayıtları sadece görüntülenebilir.",
            text_color=t["muted"],
        ).pack(anchor="w", pady=(4, 0))

        body = ctk.CTkFrame(self, fg_color=t["panel"], corner_radius=14)
        body.grid(row=1, column=0, sticky="nsew", padx=22, pady=10)
        body.grid_columnconfigure(0, weight=1)

        self.status_labels = {}
        for idx, (key, label) in enumerate(
            [
                ("last_local_backup", "Son yerel yedek"),
                ("last_backup_status", "Son yedek durumu"),
            ]
        ):
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.grid(row=idx, column=0, sticky="ew", padx=18, pady=(14 if idx == 0 else 4, 4))
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=label, width=150, anchor="w", text_color=t["muted"]).grid(row=0, column=0, sticky="w")
            value = ctk.CTkLabel(row, text="-", anchor="w", text_color=t["text"], wraplength=520, justify="left")
            value.grid(row=0, column=1, sticky="ew", padx=(10, 0))
            self.status_labels[key] = value

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=18, pady=20)
        for col in range(3):
            actions.grid_columnconfigure(col, weight=1)

        buttons = [
            ("Şimdi Yedek Al", self._backup_now, t["accent"]),
            ("Yedekleri Görüntüle", self._open_archives, t["panel2"]),
            ("Yedekten Geri Yükle", self._restore, t["danger"]),
            ("Admin Şifresi Değiştir", self._change_password, t["panel2"]),
        ]
        for index, (text, command, color) in enumerate(buttons):
            ctk.CTkButton(
                actions,
                text=text,
                height=44,
                corner_radius=10,
                fg_color=color,
                text_color="white" if color != t["panel2"] else t["text"],
                hover_color=t.get("accent_hover", color),
                command=command,
            ).grid(row=index // 3, column=index % 3, sticky="ew", padx=6, pady=6)

        self._refresh_status()

    def _refresh_status(self):
        status = self.manager.get_status()
        for key, label in self.status_labels.items():
            label.configure(text=status.get(key) or "-")

    def _backup_now(self):
        def done(result):
            self._refresh_status()
            if result.ok:
                messagebox.showinfo("Yedekleme", result.message, parent=self)
            else:
                messagebox.showerror("Yedekleme", result.message, parent=self)

        _run_ui_background(self, self.app, "manual_backup", lambda: self.manager.create_backup("manual"), done, "Yedekleme")

    def _choose_drive(self):
        messagebox.showinfo("Yedekleme", "Google Drive yedekleme pasif. Yerel yedekleme kullanılacak.")

    def _sync_drive(self):
        messagebox.showinfo("Yedekleme", "Google Drive yedekleme pasif. Yerel yedekleme kullanılacak.")

    def _open_archives(self):
        if not self._require_archive_password():
            return
        ArchiveViewerDialog(self, self.app)

    def _restore(self):
        if not self._require_archive_password():
            return
        backup_path = filedialog.askopenfilename(
            title="Geri yüklenecek yedeği seç",
            initialdir=str(self.manager.local_root),
            filetypes=[("SQLite yedekleri", "*.db"), ("Tüm dosyalar", "*.*")],
        )
        if not backup_path:
            return
        ok = messagebox.askyesno(
            "Yedekten Geri Yükle",
            "Bu işlem mevcut veriyi seçilen yedekle değiştirecek.\nDevam etmeden önce mevcut verinin emergency yedeği alınacak.\n\nDevam edilsin mi?",
        )
        if not ok:
            return
        try:
            result = self.manager.restore_backup(backup_path)
        except Exception as exc:
            messagebox.showerror("Geri Yükleme", str(exc))
            return
        self._refresh_status()
        messagebox.showinfo("Geri Yükleme", result.message)

    def _change_password(self):
        if self.security.has_password():
            old = simpledialog.askstring("Admin Şifresi", "Mevcut admin şifresi:", show="*", parent=self)
            if old is None:
                return
            ok, msg = self.security.verify_password(old)
            if not ok:
                messagebox.showwarning("Admin Şifresi", msg)
                return
        new = simpledialog.askstring("Admin Şifresi", "Yeni admin şifresi:", show="*", parent=self)
        if new is None:
            return
        repeat = simpledialog.askstring("Admin Şifresi", "Yeni şifre tekrar:", show="*", parent=self)
        if new != repeat:
            messagebox.showwarning("Admin Şifresi", "Şifreler eşleşmedi.")
            return
        try:
            self.security.set_password(new)
        except Exception as exc:
            messagebox.showerror("Admin Şifresi", str(exc))
            return
        messagebox.showinfo("Admin Şifresi", "Admin arşiv şifresi kaydedildi.")

    def _require_archive_password(self) -> bool:
        if not self.security.has_password():
            messagebox.showinfo("Admin Şifresi", "Önce arşiv ve geri yükleme için admin şifresi oluştÜrün.")
            self._change_password()
            return self.security.has_password()
        password = simpledialog.askstring("Admin Şifresi", "Admin şifresi:", show="*", parent=self)
        if password is None:
            return False
        ok, msg = self.security.verify_password(password)
        if not ok:
            messagebox.showwarning("Admin Şifresi", msg)
        return ok


class ArchiveViewerDialog(ctk.CTkToplevel):
    """Read-only browser for backup snapshots."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.manager = app.backup_manager
        self.title("Geçmiş Kayıtlar")
        self.geometry("980x680")
        t = app.theme
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.backups_by_iid = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text="Bu alan arşivdir. Kayıtlar sadece görüntülenebilir, değiştirilemez.",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=t["danger"],
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(18, 8))

        left = ctk.CTkFrame(self, fg_color=t["panel"], corner_radius=12)
        left.grid(row=1, column=0, sticky="nsew", padx=(18, 8), pady=(8, 18))
        left.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(left, columns=("month", "date"), show="tree headings", height=18)
        self.tree.heading("#0", text="Yedek")
        self.tree.heading("month", text="Ay")
        self.tree.heading("date", text="Tarih")
        self.tree.column("#0", width=260)
        self.tree.column("month", width=90)
        self.tree.column("date", width=140)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ctk.CTkFrame(self, fg_color=t["panel"], corner_radius=12)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 18), pady=(8, 18))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)
        self.text = ctk.CTkTextbox(right, wrap="word", fg_color=t.get("input", "#ffffff"), text_color=t["text"])
        self.text.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        self._load_backups()

    def _load_backups(self):
        self.tree.delete(*self.tree.get_children())
        self.backups_by_iid.clear()
        backups = self.manager.list_backups()
        if not backups:
            self.text.insert("end", "Henüz yedek bulunamadı.")
            return
        months = {}
        for backup in backups:
            month = backup["month"]
            if month not in months:
                months[month] = self.tree.insert("", "end", text=month, values=(month, ""), open=True)
            iid = self.tree.insert(months[month], "end", text=backup["name"], values=(month, backup["modified"]))
            self.backups_by_iid[iid] = backup

    def _on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        backup = self.backups_by_iid.get(selection[0])
        if not backup:
            return
        try:
            data = self.manager.read_archive_summary(backup["path"])
        except Exception as exc:
            messagebox.showerror("Arşiv", str(exc))
            return
        self._render_summary(data)

    def _render_summary(self, data):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", f"Yedek: {data['path']}\n")
        self.text.insert("end", "Bu alan arşivdir. Kayıtlar sadece görüntülenebilir, değiştirilemez.\n\n")
        sections = [
            ("Satışlar", data.get("sales", [])),
            ("Müşteriler", data.get("customers", [])),
            ("Giderler", data.get("expenses", [])),
            ("Hareketler", data.get("transactions", [])),
        ]
        for title, rows in sections:
            self.text.insert("end", f"{title} ({len(rows)} kayıt gösteriliyor)\n")
            self.text.insert("end", "-" * 72 + "\n")
            if not rows:
                self.text.insert("end", "Kayıt yok.\n\n")
                continue
            for row in rows[:80]:
                values = []
                for key, value in row.items():
                    if key in {"id", "name", "created_at", "total", "amount", "payment_method", "balance", "note", "product_name"}:
                        values.append(f"{key}: {value}")
                self.text.insert("end", " | ".join(values or [str(row)]) + "\n")
            self.text.insert("end", "\n")
        self.text.configure(state="disabled")


class AdminPasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, cashier_username=None):
        super().__init__(parent); self.app=app; self.cashier_username=cashier_username; t=app.theme
        self.title("Şifre Değiştir"); self.geometry("440x280"); _style_glass_toplevel(self,t); self.transient(parent.winfo_toplevel()); self.grab_set()
        users=[u["username"] for u in app.db.list_users()]
        self.user_var=ctk.StringVar(value=cashier_username or (users[0] if users else ""))
        self.combo=ctk.CTkComboBox(self, values=users, variable=self.user_var, **_entry_kwargs(t)); self.combo.pack(padx=20,pady=(24,8))
        self.pw=ctk.CTkEntry(self, placeholder_text="Yeni Şifre", show="*", width=320, **_entry_kwargs(t)); self.pw.pack(padx=20,pady=8)
        ctk.CTkButton(self,text="Şifreyi Güncelle",fg_color=t["accent"],command=self._ok).pack(pady=18)
    def _ok(self):
        try: self.app.update_user_password(self.user_var.get(), self.pw.get())
        except Exception as e: messagebox.showerror("Hata", str(e)); return
        messagebox.showinfo("Şifre", "Şifre güncellendi."); self.destroy()


class CustomerPasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent, app):
        super().__init__(parent); self.app=app; t=app.theme
        self.title("Müşteri İşlem Şifresi"); self.geometry("440x240"); _style_glass_toplevel(self,t); self.transient(parent.winfo_toplevel()); self.grab_set()
        ctk.CTkLabel(self, text="Müşteri silme ve kritik müşteri işlemleri için onay şifresi", text_color=t["muted"], wraplength=360).pack(padx=20, pady=(24, 10))
        self.pw=ctk.CTkEntry(self, placeholder_text="Yeni müşteri işlem şifresi", show="*", width=320, **_entry_kwargs(t)); self.pw.pack(padx=20,pady=8)
        ctk.CTkButton(self,text="Şifreyi Kaydet",fg_color=t["accent"],hover_color=t["accent_hover"],command=self._ok).pack(pady=18)
    def _ok(self):
        value = self.pw.get().strip()
        if len(value) < 4:
            messagebox.showerror("Hata", "Müşteri işlem şifresi en az 4 karakter olmalı."); return
        self.app.db.set_settings({"customer_operation_password": value})
        messagebox.showinfo("Şifre", "Müşteri işlem şifresi güncellendi."); self.destroy()


class SyncStatusDialog(ctk.CTkToplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        t = app.theme
        self.title("Senkron Durumu")
        self.geometry("760x520")
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(top, text="Senkron Durumu", font=ctk.CTkFont(size=22, weight="bold"), text_color=t["text"]).pack(side="left")
        ctk.CTkButton(top, text="Yenile", fg_color=t["panel2"], command=self._refresh).pack(side="right")
        self.box = ctk.CTkScrollableFrame(self, fg_color=t["bg"])
        self.box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self._refresh()

    def _refresh(self):
        t = self.app.theme
        for w in self.box.winfo_children():
            w.destroy()
        for status in self.app.get_manager_sync_statuses():
            color = t["muted"]
            label = "Güncel"
            if status.delayed:
                label = "Senkron gecikmiş"
                color = "#f59e0b"
                if status.last_sync:
                    try:
                        age = datetime.now() - datetime.fromisoformat(status.last_sync)
                        if age.total_seconds() > 15 * 60:
                            color = t["danger"]
                    except ValueError:
                        color = t["danger"]
            row = ctk.CTkFrame(self.box, fg_color=t["panel"], corner_radius=10, border_width=1, border_color=t["border"])
            row.pack(fill="x", pady=6)
            ctk.CTkLabel(row, text=status.username, font=ctk.CTkFont(size=16, weight="bold"), text_color=t["text"]).pack(side="left", padx=12, pady=12)
            ctk.CTkLabel(row, text=(status.last_sync.replace("T", " ")[:19] if status.last_sync else "-"), text_color=t["muted"]).pack(side="left", padx=12)
            ctk.CTkLabel(row, text=label, text_color=color, font=ctk.CTkFont(size=13, weight="bold")).pack(side="right", padx=12)


class StockAdjustmentDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, db=None, cashier_id=None, username=None):
        super().__init__(parent)
        self.app = app
        self.db = db or app.db
        self.cashier_id = cashier_id
        self.username = username
        t = app.theme
        self.title("Stok Düzenleme")
        self.geometry("520x300")
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        products = self.db.list_all_products(active_only=False, cashier_id=cashier_id)
        self.product_map = {f"{p['id']} - {p['name']}": p for p in products}
        ctk.CTkLabel(self, text="Stok düzeltmesi", font=ctk.CTkFont(size=22, weight="bold"), text_color=t["text"]).pack(anchor="w", padx=22, pady=(20, 10))
        self.product_var = ctk.StringVar(value=next(iter(self.product_map), ""))
        self.product = ctk.CTkComboBox(self, values=list(self.product_map.keys()) or ["Ürün yok"], variable=self.product_var, width=460)
        self.product.pack(padx=22, pady=6)
        self.qty = ctk.CTkEntry(self, placeholder_text="Düzeltme miktarı (+/-)", width=460, **_entry_kwargs(t))
        self.qty.pack(padx=22, pady=6)
        self.note = ctk.CTkEntry(self, placeholder_text="Not", width=460, **_entry_kwargs(t))
        self.note.pack(padx=22, pady=6)
        ctk.CTkButton(self, text="Kaydet", fg_color=t["accent"], command=self._save).pack(pady=18)

    def _save(self):
        key = self.product_var.get()
        product = self.product_map.get(key)
        if not product:
            messagebox.showwarning("Stok", "Ürün seçilmedi.")
            return
        try:
            new_stock = float(product.get("stock") or 0) + float(self.qty.get())
            self.db.update_product(
                product["id"],
                product["name"],
                product["category"],
                product["price"],
                new_stock,
                product.get("active", 1),
                product.get("icon", ""),
                cashier_id=self.cashier_id,
            )
            if self.username:
                if hasattr(self.app, "run_background_io"):
                    self.app.run_background_io("stock_export", lambda: self.app.export_cashier_files(self.username))
                else:
                    self.app.export_cashier_files(self.username)
        except Exception as exc:
            messagebox.showerror("Stok", str(exc))
            return
        messagebox.showinfo("Stok", "Stok düzeltmesi kaydedildi.")
        self.destroy()


class ProductManageDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, on_change=None, user=None, embedded=False, db=None, manage_cashier_id=None, manage_username=None):
        self.embedded = embedded
        if embedded:
            self.root = ctk.CTkFrame(parent, fg_color=app.theme["panel"])
            self.root.pack(fill="both", expand=True)
        else:
            super().__init__(parent); self.root = self; self.title("Ürün Yönetimi"); self.geometry("760x520"); _style_glass_toplevel(self, app.theme); self.transient(parent.winfo_toplevel()); self.grab_set()
        self.app=app; self.db=db or app.db; self.on_change=on_change; self.user=user or {}; self.manage_username=manage_username
        self.cashier_id=manage_cashier_id if manage_cashier_id is not None else (None if self.user.get("user_type")=="admin" else self.user.get("id"))
        self.is_admin = self.user.get("user_type") == "admin"
        t=app.theme
        self.show_archived = ctk.BooleanVar(value=False)
        bf=ctk.CTkFrame(self.root, fg_color="transparent"); bf.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(bf,text="Ekle",fg_color=t["success"],command=self._add).pack(side="left",padx=4)
        ctk.CTkButton(bf,text="Düzenle",fg_color=t["accent"],command=self._edit).pack(side="left",padx=4)
        ctk.CTkButton(bf,text="Pasifle",fg_color=t["danger"],command=self._deact).pack(side="left",padx=4)
        if self.is_admin:
            self.show_archived = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(
                bf,
                text="Pasif ürünleri göster",
                variable=self.show_archived,
                command=self._refresh,
                text_color=t["muted"],
            ).pack(side="left", padx=12)
        self.tree=ttk.Treeview(self.root, columns=("id","name","category","price","stock","active"), show="headings")
        for c,h,w in [("id","ID",60),("name","Ürün",220),("category","Kategori",130),("price","Fiyat",90),("stock","Stok",80),("active","Durum",90)]: self.tree.heading(c,text=h); self.tree.column(c,width=w)
        self.tree.pack(fill="both", expand=True, padx=16, pady=(0,16)); self.tree.bind("<<TreeviewSelect>>", self._on_sel); self.selected_product_id=None; self._refresh()
        bind_ctrl_shortcut(self.root, "<Control-u>", self._add, "Ürün")
        bind_ctrl_shortcut(self.root, "<Control-U>", self._add, "Ürün")
    def _export_after_change(self):
        username = self.manage_username or (self.user.get("username") if self.user.get("user_type") != "admin" else None)
        if not username:
            return
        if hasattr(self.app, "run_background_io"):
            self.app.run_background_io("product_export", lambda: self.app.export_cashier_files(username))
        else:
            self.app.export_cashier_files(username)
    @measure("urun_verisi_yukleme_suresi", lambda self: "ProductManageDialog._refresh")
    def _refresh(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        effective_stock = self.app.effective_stock_map() if self.is_admin and self.cashier_id is None else {}
        include_archived = bool(self.is_admin and self.show_archived.get())
        for p in sorted(self.db.list_all_products(active_only=False, cashier_id=self.cashier_id, include_archived=include_archived), key=lambda x:x["id"]):
            stock_value = effective_stock.get(int(p["id"]), p["stock"])
            archived = bool(p.get("archived") or not p.get("is_active", 1))
            status = "Arşiv" if archived else ("Aktif" if p["active"] else "Pasif")
            self.tree.insert("","end",iid=str(p["id"]),values=(p["id"],p["name"],p["category"],money(p["price"]),stock_value,status))
    def _on_sel(self,_e=None):
        sel=self.tree.selection(); self.selected_product_id=int(sel[0]) if sel else None
    def _add(self):
        ProductEditDialog(self.root,self.app,None,lambda d:self._save(None,d))
    def _edit(self):
        if not self.selected_product_id: return
        p=next((dict(x) for x in self.db.list_all_products(active_only=False,cashier_id=self.cashier_id) if x["id"]==self.selected_product_id),None)
        if p: ProductEditDialog(self.root,self.app,p,lambda d:self._save(p["id"],d))
    def _save(self,pid,d):
        if d.get("deleted"):
            self.db.delete_product(int(d.get("id") or pid), cashier_id=self.cashier_id)
            self._export_after_change()
            self._refresh(); self.on_change and self.on_change()
            messagebox.showinfo("Ürün", "Ürün pasifleştirildi.")
            return
        if pid:
            self.db.update_product(pid,d["name"],d["category"],d["price"],d["stock"],d.get("active",1),d.get("icon",""),cashier_id=self.cashier_id)
        else:
            self.db.add_product(d["name"],d["category"],d["price"],d["stock"],d.get("icon",""),cashier_id=self.cashier_id)
        self._export_after_change()
        self._refresh(); self.on_change and self.on_change()
        messagebox.showinfo("Ürün", "Ürün kaydedildi.")
    def _deact(self):
        if not self.selected_product_id: return
        if not messagebox.askyesno("Onay", "Seçili ürün pasifleştirilsin mi?"):
            return
        self.db.delete_product(self.selected_product_id, cashier_id=self.cashier_id)
        self._export_after_change()
        self._refresh(); self.on_change and self.on_change()


class AppTitleDialog(ctk.CTkToplevel):
    def __init__(self, parent, app):
        super().__init__(parent); self.app=app; t=app.theme; self.title("Uygulama Başlığı"); self.geometry("400x160"); _style_glass_toplevel(self,t); self.transient(parent.winfo_toplevel()); self.grab_set(); self.e=ctk.CTkEntry(self,width=320,**_entry_kwargs(t)); self.e.pack(padx=20,pady=(24,8)); self.e.insert(0, app.db.get_setting("app_title","Matadors Club")); ctk.CTkButton(self,text="Kaydet",fg_color=t["accent"],command=self._ok).pack(pady=12)
    def _ok(self): self.app.db.set_settings({"app_title": self.e.get().strip() or "Matadors Club"}); self.destroy()


class AdminSettingsPage(ctk.CTkFrame):
    """Sol ikonlu menu + sağda temiz içerik (varsayılan: kasa kartları)."""

    @measure("dashboard_render_suresi", lambda self, parent, app, user, db=None: f"AdminSettingsPage user={user.get('username') if isinstance(user, dict) else ''}")
    def __init__(self, parent, app, user: dict, db=None):
        t = app.theme
        super().__init__(parent, fg_color=t["bg"])
        self.app = app
        self.user = user
        self.db = db or app.db
        self.sidebar_buttons = {}
        self.active_sidebar_key = "kasalar"

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        sb = t.get("sidebar", t["panel"])
        self.sidebar = ctk.CTkFrame(self, fg_color=sb, width=236, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        side_txt = "#ededed"
        side_muted = "#a1a1aa"

        head = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(18, 14))
        lg = load_brand_logo(app, size=(56, 56))
        if lg:
            ctk.CTkLabel(head, text="", image=lg).pack(pady=(0, 8))
        ctk.CTkLabel(head, text="Yönetici", font=ctk.CTkFont(size=11), text_color=side_muted).pack()
        ctk.CTkLabel(head, text="Matadors Club", font=ctk.CTkFont(size=17, weight="bold"), text_color=side_txt).pack()

        self._sidebar_btn_text = side_txt

        self._side_btn("kasalar", "\U0001f4bc  Kasalar", self._show_kasalar)
        self._side_btn("reports", "\U0001f4c5  Geçmiş Raporlar", self._show_reports)
        self._side_btn("defter_daily", "\U0001f4d2  Defter Hareketleri", self._show_defter_daily)
        self._side_btn("defter_balance", "\U0001f4b0  Defter", self._show_defter_balance)

        ctk.CTkFrame(self.sidebar, fg_color=t["border"], height=1).pack(fill="x", padx=16, pady=14)

        self._side_btn_action("Veri Güvenliği / Yedekleme", lambda: BackupSettingsDialog(self, self.app))
        self._side_btn_action("\U0001f511  Şifre Değiştir", lambda: AdminPasswordDialog(self, self.app))
        self._side_btn_action("\U0001f510  Müşteri Şifre Değiştir", lambda: CustomerPasswordDialog(self, self.app))
        self._side_btn_action("\U0001f504  Şifreleri Sıfırla", self._reset_all_passwords)

        self.sidebar.grid_forget()

        self.content = ctk.CTkFrame(self, fg_color=t["bg"])
        self.content.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        self.settings_nav = ctk.CTkFrame(self.content, fg_color="transparent")
        self.settings_nav.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.settings_nav.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="settings_nav")
        self.sidebar_buttons = {}
        self._settings_nav_btn("kasalar", "Kasalar", self._show_kasalar, 0)
        self._settings_nav_btn("daily_report", "Günlük", self._show_daily_report, 1)
        self._settings_nav_btn("reports", "Raporlar", self._show_reports, 2)
        self._settings_nav_btn("defter_daily", "Defter Hrk.", self._show_defter_daily, 3)
        self._settings_nav_btn("defter_balance", "Defter", self._show_defter_balance, 4)

        actions = ctk.CTkFrame(self.content, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for col in range(5):
            actions.grid_columnconfigure(col, weight=1, uniform="settings_actions")
        self._settings_action(actions, "Veri Güvenliği", lambda: BackupSettingsDialog(self, self.app), 0)
        self._settings_action(actions, "Şifre Değiştir", lambda: AdminPasswordDialog(self, self.app), 1)
        self._settings_action(actions, "Müşteri Şifresi", lambda: CustomerPasswordDialog(self, self.app), 2)
        self._settings_action(actions, "Web Paneli", lambda: WebPanelDialog(self, self.app, self.user), 3)
        self._settings_action(actions, "Şifreleri Sıfırla", self._reset_all_passwords, 3)

        self.view_kasalar = ctk.CTkFrame(self.content, fg_color="transparent")
        self.view_daily_report = ctk.CTkFrame(self.content, fg_color="transparent")
        self.view_reports = ctk.CTkFrame(self.content, fg_color="transparent")
        self.view_defter_daily = ctk.CTkFrame(self.content, fg_color="transparent")
        self.view_defter_balance = ctk.CTkFrame(self.content, fg_color="transparent")

        self._build_kasalar_view()
        self._build_daily_report_view()
        self._build_reports_view()
        self._build_defter_daily_view()
        self._build_defter_balance_view()

        self._highlight_sidebar("kasalar")
        self._raise_view(self.view_kasalar)
        self._refresh_kasa_cards()

    def _side_btn(self, key: str, label: str, command):
        t = self.app.theme
        txt = getattr(self, "_sidebar_btn_text", t["text"])
        btn = ctk.CTkButton(
            self.sidebar,
            text=label,
            anchor="w",
            height=46,
            corner_radius=10,
            fg_color="transparent",
            text_color=txt,
            hover_color=t["panel2"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self._sidebar_nav(key, command),
        )
        btn.pack(fill="x", padx=12, pady=4)
        self.sidebar_buttons[key] = btn

    def _side_btn_action(self, label: str, command):
        t = self.app.theme
        txt = getattr(self, "_sidebar_btn_text", t["text"])
        btn = ctk.CTkButton(
            self.sidebar,
            text=label,
            anchor="w",
            height=44,
            corner_radius=10,
            fg_color="transparent",
            text_color=txt,
            hover_color=t["accent_hover"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=command,
        )
        btn.pack(fill="x", padx=12, pady=3)

    def _settings_nav_btn(self, key: str, label: str, command, col: int):
        t = self.app.theme
        btn = ctk.CTkButton(
            self.settings_nav,
            text=label,
            height=34,
            corner_radius=8,
            fg_color=t.get("sidebar", "#111111"),
            text_color="white",
            hover_color=t["accent_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._sidebar_nav(key, command),
        )
        btn.grid(row=0, column=col, sticky="ew", padx=4, pady=4)
        self.sidebar_buttons[key] = btn

    def _settings_action(self, parent, label: str, command, col: int):
        t = self.app.theme
        ctk.CTkButton(
            parent,
            text=label,
            height=34,
            corner_radius=8,
            fg_color=t.get("sidebar", "#111111"),
            text_color="white",
            hover_color=t["accent_hover"],
            font=ctk.CTkFont(size=11, weight="bold"),
            command=command,
        ).grid(row=0, column=col, sticky="ew", padx=4, pady=4)

    def _sidebar_nav(self, key: str, fn):
        self._highlight_sidebar(key)
        fn()

    def _highlight_sidebar(self, key: str):
        self.active_sidebar_key = key
        t = self.app.theme
        idle_txt = getattr(self, "_sidebar_btn_text", t["text"])
        for k, btn in self.sidebar_buttons.items():
            if k == key:
                btn.configure(fg_color=t["accent"], text_color="white", hover_color=t["accent_hover"])
            else:
                if btn.winfo_parent().endswith("sidebar"):
                    btn.configure(fg_color="transparent", text_color=idle_txt, hover_color=t["panel2"])
                else:
                    btn.configure(fg_color=t.get("sidebar", "#111111"), text_color="white", hover_color=t["accent_hover"])

    def _raise_view(self, frame):
        for v in (self.view_kasalar, self.view_daily_report, self.view_reports, self.view_defter_daily, self.view_defter_balance):
            v.grid_forget()
        frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

    def _show_kasalar(self):
        self._raise_view(self.view_kasalar)
        self._refresh_kasa_cards()

    def _show_reports(self):
        self._raise_view(self.view_reports)
        self._show_rep()

    def _show_daily_report(self):
        self._raise_view(self.view_daily_report)
        self._show_daily_live_report()


    def _reset_all_passwords(self):
        """Reset all passwords to defaults."""
        if not messagebox.askyesno(
            "Şifreleri Sıfırla",
            "Tüm şifreler varsayılan değerlere sıfırlanacak:\n\n"
            "Admin: admin123\n"
            "Emin misiniz?"
        ):
            return
        try:
            self.db.reset_all_passwords()
            messagebox.showinfo("Başarılı", "Tüm şifreler başarıyla sıfırlandı!\n\nAdmin: admin123")
        except Exception as e:
            messagebox.showerror("Hata", f"Şifreler sıfırlanırken hata: {e}")

    def _build_kasalar_view(self):
        t = self.app.theme
        top = ctk.CTkFrame(self.view_kasalar, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(top, text="Kasa Özeti", font=ctk.CTkFont(size=22, weight="bold"), text_color=t["text"]).pack(side="left")
        ctk.CTkButton(
            top,
            text="+ Yeni Kasa",
            width=130,
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            command=lambda: CashierCreateDialog(self, self.app, self._refresh_kasa_cards),
        ).pack(side="right")

        self.admin_summary = ctk.CTkFrame(self.view_kasalar, fg_color="transparent")
        self.admin_summary.pack(fill="x", pady=(0, 12))

        self.setup_status_box = ctk.CTkFrame(self.view_kasalar, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
        self.setup_status_box.pack(fill="x", pady=(0, 12))

        self.kasa_scroll = ctk.CTkScrollableFrame(self.view_kasalar, fg_color=t["bg"])
        self.kasa_scroll.pack(fill="both", expand=True)

    @measure("dashboard_render_suresi", lambda self: "AdminSettingsPage._refresh_kasa_cards")
    def _refresh_kasa_cards(self):
        if getattr(self, "_refreshing_kasa_cards", False):
            self._pending_kasa_refresh = True
            return
        self._refreshing_kasa_cards = True
        t = self.app.theme
        try:
            for w in self.kasa_scroll.winfo_children():
                w.destroy()

            today = datetime.now().strftime("%Y-%m-%d")
            cashiers = self.db.list_cashiers(include_archived=True)
            active_cashiers = [cashier for cashier in cashiers if _cashier_is_active(cashier)]
            for w in self.admin_summary.winfo_children():
                w.destroy()
            for w in self.setup_status_box.winfo_children():
                w.destroy()
            setup = self.app.setup_status()
            self._kasa_cards = {}
            self._kasa_summary_labels = {}
            self._kasa_cashiers_cache = {int(row["id"]): dict(row) for row in cashiers}
        except Exception as exc:
            self._refreshing_kasa_cards = False
            print(f"Kasa refresh prepare failed: {exc}")
            return
        setup_lines = [
            f"Program sürümü: {setup['app_version']}",
            f"Veri şema sürümü: {setup['data_schema_version']}",
            f"Veri klasörü: {setup['data_dir']}",
            f"Son update backup: {setup['last_update_backup'] or '-'}",
            f"Aktif profiller: {', '.join(setup['active_profiles']) if setup.get('active_profiles') else '-'}",
            f"Local cache eksik: {', '.join(setup['missing_cache']) if setup['missing_cache'] else 'yok'}",
            f"Uyumsuz/eksik: {', '.join(setup['mismatches']) if setup['mismatches'] else 'yok'}",
            "Senkron: Supabase queue aktif, yerel SQLite ana sistem",
            f"Veri okundu: {'evet' if setup['data_read'] else 'hayır'}",
            f"Kasa profilleri hazır: {'evet' if setup['cashier_ready'] else 'hayır'} ({setup['cashier_count']} adet)",
            f"Kurulum: {'tamamlandı' if setup['complete'] else 'tamamlanmadı'}",
        ]
        ctk.CTkLabel(
            self.setup_status_box,
            text="\n".join(setup_lines),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=t["text"] if setup["complete"] else "#f59e0b",
            wraplength=1100,
            justify="left",
        ).pack(anchor="w", padx=14, pady=12)
        drive_daily = self.app.manager_drive_daily_data(today)
        daily = drive_daily
        expenses = 0.0
        for title, value in [
            ("Bugun Toplam", money(daily["pos_total"] + daily["ciro"] - expenses)),
            ("Satis", f"{daily['pos_sale_count']} adet"),
            ("Bakiye Yukleme", money(daily["yukleme"])),
            ("Aktif Kasa", str(len(active_cashiers))),
        ]:
            box = ctk.CTkFrame(self.admin_summary, fg_color=t.get("glass", t["panel"]), corner_radius=12, border_width=1, border_color=t["border"])
            box.pack(side="left", fill="x", expand=True, padx=6)
            ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color=t["muted"]).pack(anchor="w", padx=14, pady=(12, 2))
            value_label = ctk.CTkLabel(box, text=value, font=ctk.CTkFont(size=20, weight="bold"), text_color=t["text"])
            value_label.pack(anchor="w", padx=14, pady=(0, 12))
            self._kasa_summary_labels[title] = value_label
        if not cashiers:
            ctk.CTkLabel(self.kasa_scroll, text="Henüz kasa kullanıcısı yok.", text_color=t["muted"]).pack(pady=40)
            return

        summaries = {item["cashier_id"]: item for item in drive_daily["summaries"]}
        sync_statuses = {item.username: item for item in self.app.get_manager_sync_statuses()}

        grid = ctk.CTkFrame(self.kasa_scroll, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        for i, k in enumerate(cashiers):
            is_active = _cashier_is_active(k)
            summary = summaries.get(k["id"], {"ciro": 0.0, "yukleme": 0.0, "pos_total": 0.0})
            gunluk = float(summary["pos_total"]) + float(summary["ciro"])

            card = ctk.CTkFrame(
                grid,
                fg_color=t["panel"],
                corner_radius=16,
                border_width=1,
                border_color=t["border"],
                width=300,
                height=188,
            )
            card.grid(row=i // 2, column=i % 2, padx=12, pady=12, sticky="nw")

            def open_detail(event=None, kk=k):
                CashierDetailDialog(self, self.app, kk, self._refresh_kasa_cards)

            card.bind("<Button-1>", open_detail)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=18, pady=16)
            inner.bind("<Button-1>", open_detail)

            # Header row with name and delete button
            header = ctk.CTkFrame(inner, fg_color="transparent")
            header.pack(fill="x", anchor="w")

            name_l = ctk.CTkLabel(
                header,
                text=k["full_name"],
                font=ctk.CTkFont(size=20, weight="bold"),
                text_color=t["text"],
            )
            name_l.pack(side="left")
            name_l.bind("<Button-1>", open_detail)

            if k.get("user_type") != "admin":
                action_btn = ctk.CTkButton(
                    header,
                    text="Pasifleştir" if is_active else "Aktif Et",
                    width=86,
                    height=28,
                    fg_color=t["danger"] if is_active else t["success"],
                    hover_color="#991b1b" if is_active else t.get("success_hover", t["success"]),
                    font=ctk.CTkFont(size=11),
                )
                action_btn.configure(command=lambda kk=k, btn=action_btn: self._toggle_cashier_active(kk, btn))
                action_btn.pack(side="right")
            else:
                action_btn = None

            sub = ctk.CTkLabel(inner, text=f"@{k['username']}", text_color=t["muted"], font=ctk.CTkFont(size=12))
            sub.pack(anchor="w", pady=(4, 12))
            sub.bind("<Button-1>", open_detail)

            status_l = ctk.CTkLabel(
                inner,
                text="Aktif" if is_active else "Pasif",
                text_color=t["success"] if is_active else t["danger"],
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            status_l.pack(anchor="w", pady=(0, 6))
            status_l.bind("<Button-1>", open_detail)
            self._kasa_cards[int(k["id"])] = {"status": status_l, "button": action_btn, "cashier": k}

            sync_status = sync_statuses.get(k["username"])
            sync_text = "Son senkron: -"
            sync_color = t["muted"]
            if sync_status and sync_status.last_sync:
                sync_text = f"Son senkron: {sync_status.last_sync.replace('T', ' ')[:16]}"
                if sync_status.delayed:
                    sync_text += " - senkron gecikmiş"
                    sync_color = "#f59e0b"
                    try:
                        if (datetime.now() - datetime.fromisoformat(sync_status.last_sync)).total_seconds() > 15 * 60:
                            sync_color = t["danger"]
                    except ValueError:
                        sync_color = t["danger"]
            elif sync_status and sync_status.delayed:
                sync_text = "Son senkron yok - senkron gecikmiş"
                sync_color = t["danger"]
            sync_l = ctk.CTkLabel(inner, text=sync_text, text_color=sync_color, font=ctk.CTkFont(size=11))
            sync_l.pack(anchor="w", pady=(0, 6))
            sync_l.bind("<Button-1>", open_detail)
            if sync_status and sync_status.message:
                warn_l = ctk.CTkLabel(
                    inner,
                    text=sync_status.message[:90],
                    text_color="#f59e0b" if sync_color != t["danger"] else t["danger"],
                    font=ctk.CTkFont(size=10),
                    wraplength=250,
                    justify="left",
                )
                warn_l.pack(anchor="w", pady=(0, 6))
                warn_l.bind("<Button-1>", open_detail)

            ciro_l = ctk.CTkLabel(
                inner,
                text=f"Gün Sonu Ciro  {money(gunluk)}",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color=t["success"],
            )
            ciro_l.pack(anchor="w")
            ciro_l.bind("<Button-1>", open_detail)

            hint = ctk.CTkLabel(inner, text="Detay için tıkla", text_color=t["muted"], font=ctk.CTkFont(size=11))
            hint.pack(anchor="w", pady=(8, 0))
            hint.bind("<Button-1>", open_detail)
        self._refreshing_kasa_cards = False
        if getattr(self, "_pending_kasa_refresh", False):
            self._pending_kasa_refresh = False
            self.after(120, self._refresh_kasa_cards)

    def _toggle_cashier_active(self, cashier: dict, button=None):
        is_active = _cashier_is_active(cashier)
        action = "Pasifleştir" if is_active else "Aktif Et"
        if not messagebox.askyesno(
            action,
            f"@{cashier.get('username', '')} kasası {'pasifleştirilsin' if is_active else 'aktif edilsin'} mi?",
            parent=self,
        ):
            return
        if button:
            button.configure(state="disabled", text="İşleniyor...")

        def work():
            if is_active:
                return self.app.passivate_cashier_profile(cashier["id"])
            return self.app.activate_cashier_profile(cashier["id"])

        def done(updated):
            self._apply_cashier_active_result(cashier, updated, button)
            messagebox.showinfo("Kasa", f"Kasa {'pasifleştirildi' if is_active else 'aktif edildi'}.", parent=self)

        def failed(exc):
            if button:
                button.configure(state="normal", text=action)
            messagebox.showerror("Kasa", str(exc), parent=self)

        self.app.run_background_io("cashier_active_toggle", work, done, failed)

    def _apply_cashier_active_result(self, old_cashier: dict, updated: dict, button=None):
        cashier = dict(old_cashier)
        cashier.update(updated or {})
        cashier_id = int(cashier["id"])
        is_active = _cashier_is_active(cashier)
        card = getattr(self, "_kasa_cards", {}).get(cashier_id, {})
        if card.get("status"):
            card["status"].configure(
                text="Aktif" if is_active else "Pasif",
                text_color=self.app.theme["success"] if is_active else self.app.theme["danger"],
            )
        target_button = button or card.get("button")
        if target_button:
            target_button.configure(
                state="normal",
                text="Pasifleştir" if is_active else "Aktif Et",
                fg_color=self.app.theme["danger"] if is_active else self.app.theme["success"],
                hover_color="#991b1b" if is_active else self.app.theme.get("success_hover", self.app.theme["success"]),
            )
            target_button.configure(command=lambda kk=cashier, btn=target_button: self._toggle_cashier_active(kk, btn))
        card["cashier"] = cashier
        self._kasa_cards[cashier_id] = card
        if hasattr(self, "_kasa_cashiers_cache"):
            self._kasa_cashiers_cache[cashier_id] = cashier
            active_count = sum(1 for row in self._kasa_cashiers_cache.values() if _cashier_is_active(row))
            label = getattr(self, "_kasa_summary_labels", {}).get("Aktif Kasa")
            if label:
                label.configure(text=str(active_count))

    def _start_delete_cashier(self, cashier: dict, button=None):
        messagebox.showinfo("Kasa", "Kalıcı silme devre dışı. Kasa için Pasifleştir/Aktif Et kullanın.", parent=self)

    def _build_reports_view(self):
        t = self.app.theme
        bar = ctk.CTkFrame(self.view_reports, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        self.date_picker = DateEntry(bar, date_pattern="yyyy-mm-dd")
        self.date_picker.pack(side="left", padx=(0, 10))
        ctk.CTkButton(bar, text="Listele", fg_color=t["panel2"], command=self._show_rep).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="PDF İndir", fg_color=t["accent"], hover_color=t["accent_hover"], command=self._pdf_rep).pack(side="left", padx=4)

        self.rep_box = ctk.CTkTextbox(self.view_reports, fg_color=t["input"], text_color=t["text"], border_color=t["border"])
        self.rep_box.pack(fill="both", expand=True)

    def _build_daily_report_view(self):
        t = self.app.theme
        bar = ctk.CTkFrame(self.view_daily_report, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(bar, text="Bugünün Canlı Raporu", font=ctk.CTkFont(size=20, weight="bold"), text_color=t["text"]).pack(side="left")
        ctk.CTkButton(bar, text="Yenile", fg_color=t["panel2"], text_color=t["text"], command=self._show_daily_live_report).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="PDF İndir", fg_color=t["accent"], hover_color=t["accent_hover"], command=self._pdf_daily_live_report).pack(side="right", padx=4)
        self.daily_report_box = ctk.CTkTextbox(self.view_daily_report, fg_color=t["input"], text_color=t["text"], border_color=t["border"])
        self.daily_report_box.pack(fill="both", expand=True)

    @measure("dashboard_render_suresi", lambda self: "AdminSettingsPage._show_daily_live_report")
    def _show_daily_live_report(self):
        today = datetime.now().strftime("%Y-%m-%d")
        r = self.app.manager_drive_daily_data(today)
        self.daily_report_box.delete("1.0", "end")
        self.daily_report_box.insert(
            "end",
            f"Günlük Rapor: {today}\nPOS: {money(r['pos_total'])} | Bakiye harcama: {money(r['ciro'])} | Yüklenme: {money(r['yukleme'])}\n\n",
        )
        for tx in r["transactions"][:120]:
            self.daily_report_box.insert(
                "end",
                f"{tx['created_at'][11:16]} | {tx['cashier_name']} | {tx['customer_name']} | {tx['action_type']} | {money(tx['amount'])}\n",
            )

    @measure("pdf_olusturma_suresi", lambda self: "AdminSettingsPage._pdf_daily_live_report")
    def _pdf_daily_live_report(self):
        _run_ui_background(
            self,
            self.app,
            "admin_daily_pdf",
            lambda: self.app.create_report_pdf(datetime.now().strftime("%Y-%m-%d"), None),
            lambda path: messagebox.showinfo("PDF", path, parent=self),
            "PDF",
        )

    def selected_date(self):
        return self.date_picker.get_date().strftime("%Y-%m-%d")

    @measure("dashboard_render_suresi", lambda self: "AdminSettingsPage._show_rep")
    def _show_rep(self):
        date_str = self.selected_date()
        self.rep_box.delete("1.0", "end")
        if date_str >= datetime.now().strftime("%Y-%m-%d"):
            self.rep_box.insert(
                "end",
                "Geçmiş Raporlar yalnızca tamamlanmış günlerin arşiv çıktısı içindir.\n"
                "Bugünün canlı raporu Günlük Rapor ekranından alınmalıdır.",
            )
            return
        r = self.app.manager_drive_daily_data(date_str)
        self.rep_box.insert(
            "end",
            f"Arşiv Raporu: {r['date']}\nPOS: {money(r['pos_total'])} | Bakiye harcama: {money(r['ciro'])} | Yüklenme: {money(r['yukleme'])}\n\n",
        )
        for tx in r["transactions"][:80]:
            self.rep_box.insert(
                "end",
                f"{tx['created_at'][11:16]} | {tx['cashier_name']} | {tx['customer_name']} | {tx['action_type']} | {money(tx['amount'])}\n",
            )

    @measure("pdf_olusturma_suresi", lambda self: "AdminSettingsPage._pdf_rep")
    def _pdf_rep(self):
        date_str = self.selected_date()
        if date_str >= datetime.now().strftime("%Y-%m-%d"):
            messagebox.showwarning("Geçmiş Raporlar", "Bugünün raporu bu ekrandan alınmaz. Lütfen Günlük Rapor ekranını kullanın.")
            return
        _run_ui_background(
            self,
            self.app,
            "archive_report_pdf",
            lambda: self.app.create_report_pdf(date_str, None),
            lambda path: messagebox.showinfo("PDF", path, parent=self),
            "PDF",
        )

    def _get_cashier_name(self, cashier_id):
        """Get cashier name by ID."""
        cashier = self.db.get_user_by_id(cashier_id)
        return cashier.get("full_name", cashier.get("username", "Kasa")) if cashier else "Kasa"

    def _build_defter_daily_view(self):
        """Build the DEFTER daily report view."""
        t = self.app.theme
        bar = ctk.CTkFrame(self.view_defter_daily, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))

        # Date picker
        ctk.CTkLabel(bar, text="Tarih:", text_color=t["text"], font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self.defter_daily_date = DateEntry(bar, date_pattern="yyyy-mm-dd")
        self.defter_daily_date.pack(side="left", padx=(0, 10))

        # Cashier filter
        ctk.CTkLabel(bar, text="Kasa:", text_color=t["text"], font=ctk.CTkFont(size=12)).pack(side="left", padx=(20, 8))
        self.defter_daily_cashier_var = ctk.StringVar(value="Tüm Kasalar")
        self.defter_daily_cashier = ctk.CTkComboBox(bar, width=150, values=["Tüm Kasalar"], state="readonly", variable=self.defter_daily_cashier_var)
        self.defter_daily_cashier.pack(side="left", padx=(0, 10))

        ctk.CTkButton(bar, text="Listele", fg_color=t["panel2"], command=self._show_defter_daily_report).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="PDF İndir", fg_color=t["accent"], hover_color=t["accent_hover"], command=self._pdf_defter_daily).pack(side="left", padx=4)

        # Report scrollable frame
        self.defter_daily_scroll = ctk.CTkScrollableFrame(self.view_defter_daily, fg_color=t["bg"])
        self.defter_daily_scroll.pack(fill="both", expand=True)

    def _build_defter_balance_view(self):
        """Build the DEFTER balance report view."""
        t = self.app.theme
        bar = ctk.CTkFrame(self.view_defter_balance, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))

        # Cashier filter only
        ctk.CTkLabel(bar, text="Kasa:", text_color=t["text"], font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self.defter_balance_cashier_var = ctk.StringVar(value="Tüm Kasalar")
        self.defter_balance_cashier = ctk.CTkComboBox(bar, width=150, values=["Tüm Kasalar"], state="readonly", variable=self.defter_balance_cashier_var)
        self.defter_balance_cashier.pack(side="left", padx=(0, 10))

        ctk.CTkButton(bar, text="Listele", fg_color=t["panel2"], command=self._show_defter_balance_report).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="PDF İndir", fg_color=t["accent"], hover_color=t["accent_hover"], command=self._pdf_defter_balance).pack(side="left", padx=4)

        # Report scrollable frame
        self.defter_balance_scroll = ctk.CTkScrollableFrame(self.view_defter_balance, fg_color=t["bg"])
        self.defter_balance_scroll.pack(fill="both", expand=True)

    def _show_defter_daily(self):
        """Show DEFTER daily view and refresh cashier list."""
        self._raise_view(self.view_defter_daily)
        self._refresh_defter_daily_cashier_list()
        self._show_defter_daily_report()

    def _show_defter_balance(self):
        """Show DEFTER balance view and refresh cashier list."""
        self._raise_view(self.view_defter_balance)
        self._refresh_defter_balance_cashier_list()
        self._show_defter_balance_report()

    def _refresh_defter_daily_cashier_list(self):
        """Refresh cashier dropdown for DEFTER daily view."""
        cashiers = self.db.list_cashiers()
        cashier_values = ["Tüm Kasalar"] + [f"{c['id']} - {c['full_name']}" for c in cashiers]
        self.defter_daily_cashier.configure(values=cashier_values)
        self.defter_daily_cashier.set("Tüm Kasalar")

    def _refresh_defter_balance_cashier_list(self):
        """Refresh cashier dropdown for DEFTER balance view."""
        cashiers = self.db.list_cashiers()
        cashier_values = ["Tüm Kasalar"] + [f"{c['id']} - {c['full_name']}" for c in cashiers]
        self.defter_balance_cashier.configure(values=cashier_values)
        self.defter_balance_cashier.set("Tüm Kasalar")

    def _get_defter_daily_cashier_id(self):
        """Get selected cashier ID for DEFTER daily view."""
        choice = self.defter_daily_cashier.get()
        if choice == "Tüm Kasalar" or not choice:
            return None
        try:
            return int(choice.split(" - ")[0])
        except ValueError:
            return None

    def _get_defter_balance_cashier_id(self):
        """Get selected cashier ID for DEFTER balance view."""
        choice = self.defter_balance_cashier.get()
        if choice == "Tüm Kasalar" or not choice:
            return None
        try:
            return int(choice.split(" - ")[0])
        except ValueError:
            return None

    def _show_defter_daily_report(self):
        """Display DEFTER movements as a chronological timeline/log."""
        date_str = self.defter_daily_date.get_date().strftime("%Y-%m-%d")
        cashier_id = self._get_defter_daily_cashier_id()
        t = self.app.theme
        for widget in self.defter_daily_scroll.winfo_children():
            widget.destroy()
        try:
            rows = self.db.defter_movements_timeline(date_str, cashier_id=cashier_id)
        except Exception as e:
            messagebox.showerror("Hata", f"Hareketler alınırken hata: {e}")
            return

        header = ctk.CTkFrame(self.defter_daily_scroll, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
        header.pack(fill="x", padx=10, pady=(10, 6))
        cashier_name = "Tüm Kasalar" if cashier_id is None else self._get_cashier_name(cashier_id)
        ctk.CTkLabel(header, text="Defter Hareketleri", font=ctk.CTkFont(size=18, weight="bold"), text_color=t["text"]).pack(anchor="w", padx=18, pady=(14, 2))
        ctk.CTkLabel(header, text=f"{date_str} | {cashier_name}", font=ctk.CTkFont(size=12), text_color=t["muted"]).pack(anchor="w", padx=18, pady=(0, 14))

        if not rows:
            ctk.CTkLabel(self.defter_daily_scroll, text="Seçilen tarihte hareket bulunamadı.", text_color=t["muted"]).pack(pady=36)
            return

        for row in rows:
            amount = float(row["amount"])
            positive = amount >= 0
            color = t.get("success", "#16A34A") if positive else t.get("danger", "#E30613")
            card = ctk.CTkFrame(self.defter_daily_scroll, fg_color=t["panel"], corner_radius=10, border_width=1, border_color=t["border"])
            card.pack(fill="x", padx=10, pady=4)
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(card, text=row["created_at"][:16].replace("T", " "), width=128, anchor="w", text_color=t["muted"]).grid(row=0, column=0, sticky="w", padx=12, pady=10)
            detail = f"{row['customer_name']} | {row['type']} | {row['detail']} | {row['cashier_name']}"
            ctk.CTkLabel(card, text=detail, anchor="w", text_color=t["text"], wraplength=620, justify="left").grid(row=0, column=1, sticky="ew", padx=8, pady=10)
            sign = "+" if positive else "-"
            ctk.CTkLabel(card, text=f"{sign}{money(abs(amount))}", width=120, anchor="e", text_color=color, font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=2, sticky="e", padx=12, pady=10)

    def _show_defter_balance_report(self):
        """Display DEFTER balance report with modern card layout."""
        cashier_id = self._get_defter_balance_cashier_id()

        try:
            report = self.db.defter_customers_balance_report(cashier_id=cashier_id, active_only=True)
        except Exception as e:
            messagebox.showerror("Hata", f"Rapor alinirken hata: {e}")
            return

        customers = report["customers"]
        summary = report["summary"]
        t = self.app.theme

        # Clear scroll frame
        for widget in self.defter_balance_scroll.winfo_children():
            widget.destroy()

        # Header card
        header_card = ctk.CTkFrame(self.defter_balance_scroll, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
        header_card.pack(fill="x", padx=10, pady=(10, 5))
        
        header_inner = ctk.CTkFrame(header_card, fg_color="transparent")
        header_inner.pack(fill="x", padx=20, pady=15)
        
        ctk.CTkLabel(header_inner, text="💰 Defter", font=ctk.CTkFont(size=18, weight="bold"), text_color=t["text"]).pack(anchor="w")
        ctk.CTkLabel(header_inner, text=f"Tarih: {datetime.now().strftime('%d.%m.%Y')}", font=ctk.CTkFont(size=12), text_color=t["muted"]).pack(anchor="w", pady=(2, 0))
        
        cashier_name = "Tüm Kasalar" if cashier_id is None else self._get_cashier_name(cashier_id)
        ctk.CTkLabel(header_inner, text=f"Kapsam: {cashier_name}", font=ctk.CTkFont(size=12), text_color=t["muted"]).pack(anchor="w")

        # Summary card
        summary_card = ctk.CTkFrame(self.defter_balance_scroll, fg_color=t["panel2"], corner_radius=12, border_width=1, border_color=t["border"])
        summary_card.pack(fill="x", padx=10, pady=5)
        
        summary_inner = ctk.CTkFrame(summary_card, fg_color="transparent")
        summary_inner.pack(fill="x", padx=20, pady=15)
        
        ctk.CTkLabel(summary_inner, text="📊 Özet", font=ctk.CTkFont(size=16, weight="bold"), text_color=t["text"]).pack(anchor="w")
        
        summary_grid = ctk.CTkFrame(summary_inner, fg_color="transparent")
        summary_grid.pack(fill="x", pady=(10, 0))
        
        ctk.CTkLabel(summary_grid, text=f"Toplam Müşteri: {summary['total_customers']}", font=ctk.CTkFont(size=13), text_color=t["text"]).pack(anchor="w")
        ctk.CTkLabel(summary_grid, text=f"Toplam Bakiye: {money(summary['total_balance'])}", font=ctk.CTkFont(size=13), text_color=t["text"]).pack(anchor="w")
        ctk.CTkLabel(summary_grid, text=f"Kullanılan Kredi: {money(summary['total_credit_used'])}", font=ctk.CTkFont(size=13), text_color=t["text"]).pack(anchor="w")
        ctk.CTkLabel(summary_grid, text=f"Toplam Defter Alışveriş: {money(summary['total_defter_purchases'])}", font=ctk.CTkFont(size=13, weight="bold"), text_color=t["accent"]).pack(anchor="w")

        # Customer cards
        if customers:
            for idx, c in enumerate(customers, 1):
                customer_card = ctk.CTkFrame(self.defter_balance_scroll, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
                customer_card.pack(fill="x", padx=10, pady=5)
                
                customer_inner = ctk.CTkFrame(customer_card, fg_color="transparent")
                customer_inner.pack(fill="x", padx=20, pady=15)
                
                # Customer header with index
                customer_header = ctk.CTkFrame(customer_inner, fg_color="transparent")
                customer_header.pack(fill="x")
                
                header_row = ctk.CTkFrame(customer_header, fg_color="transparent")
                header_row.pack(fill="x")
                
                is_test = False
                test_indicator = "🧪 " if is_test else ""
                
                # Determine balance color dot
                balance = c['balance']
                if balance < 0:
                    dot_text = "🔴"
                elif balance > 0:
                    dot_text = "🟢"
                else:
                    dot_text = "🟠"
                
                ctk.CTkLabel(header_row, text=f"#{idx}", font=ctk.CTkFont(size=16, weight="bold"), text_color=t["accent"], width=30).pack(side="left")
                ctk.CTkLabel(header_row, text=f"{test_indicator}{dot_text}", font=ctk.CTkFont(size=12)).pack(side="left")
                ctk.CTkLabel(header_row, text=f"👤 {c['name']}", font=ctk.CTkFont(size=15, weight="bold"), text_color=t["text"]).pack(side="left")
                
                if c['phone']:
                    ctk.CTkLabel(customer_header, text=f"📞 {c['phone']}", font=ctk.CTkFont(size=11), text_color=t["muted"]).pack(anchor="w", pady=(5, 8))
                
                # Balance info with color coding
                balance_color = "#E74C3C" if c['balance'] < 0 else "#27AE60"  # Red for negative, Green for positive
                
                balance_frame = ctk.CTkFrame(customer_inner, fg_color=t["input"], corner_radius=8)
                balance_frame.pack(fill="x", pady=(0, 10))
                
                balance_inner = ctk.CTkFrame(balance_frame, fg_color="transparent")
                balance_inner.pack(fill="x", padx=15, pady=10)
                
                # Balance row
                balance_row = ctk.CTkFrame(balance_inner, fg_color="transparent")
                balance_row.pack(fill="x", pady=(0, 5))
                
                ctk.CTkLabel(balance_row, text="Bakiye:", font=ctk.CTkFont(size=12), text_color=t["text"], width=60).pack(side="left")
                ctk.CTkLabel(balance_row, text=money(c['balance']), font=ctk.CTkFont(size=14, weight="bold"), text_color=balance_color).pack(side="left")
                
                # Credit limit row
                credit_row = ctk.CTkFrame(balance_inner, fg_color="transparent")
                credit_row.pack(fill="x", pady=(0, 5))
                
                ctk.CTkLabel(credit_row, text="Limit:", font=ctk.CTkFont(size=12), text_color=t["text"], width=60).pack(side="left")
                ctk.CTkLabel(credit_row, text=money(c['credit_limit']), font=ctk.CTkFont(size=12), text_color=t["text"]).pack(side="left")
                
                # Used credit row
                used_row = ctk.CTkFrame(balance_inner, fg_color="transparent")
                used_row.pack(fill="x", pady=(0, 5))
                
                ctk.CTkLabel(used_row, text="Kullanılan:", font=ctk.CTkFont(size=12), text_color=t["text"], width=60).pack(side="left")
                ctk.CTkLabel(used_row, text=money(c['credit_used']), font=ctk.CTkFont(size=12, weight="bold"), text_color="#E67E22").pack(side="left")
                
                # Total purchases row
                total_row = ctk.CTkFrame(balance_inner, fg_color="transparent")
                total_row.pack(fill="x")
                
                ctk.CTkLabel(total_row, text="Toplam:", font=ctk.CTkFont(size=12), text_color=t["text"], width=60).pack(side="left")
                ctk.CTkLabel(total_row, text=money(c['total_defter_purchases']), font=ctk.CTkFont(size=12, weight="bold"), text_color=t["accent"]).pack(side="left")
                
                # Last transaction
                if c['last_defter_date']:
                    last_frame = ctk.CTkFrame(customer_inner, fg_color=t["panel2"], corner_radius=6)
                    last_frame.pack(fill="x", pady=(5, 0))
                    
                    last_inner = ctk.CTkFrame(last_frame, fg_color="transparent")
                    last_inner.pack(fill="x", padx=12, pady=8)
                    
                    ctk.CTkLabel(last_inner, text=f"🕐 Son Defter İşlem: {c['last_defter_date']}", font=ctk.CTkFont(size=11), text_color=t["muted"]).pack(anchor="w")
        else:
            empty_card = ctk.CTkFrame(self.defter_balance_scroll, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
            empty_card.pack(fill="x", padx=10, pady=5)
            
            empty_inner = ctk.CTkFrame(empty_card, fg_color="transparent")
            empty_inner.pack(fill="x", padx=20, pady=20)
            
            ctk.CTkLabel(empty_inner, text="📭", font=ctk.CTkFont(size=24), text_color=t["muted"]).pack(anchor="w")
            ctk.CTkLabel(empty_inner, text="DEFTER kullanılan müşteri bulunmuyor", font=ctk.CTkFont(size=14), text_color=t["muted"]).pack(anchor="w", pady=(5, 0))

    def _pdf_defter_daily(self):
        """Generate PDF for DEFTER daily report."""
        date_str = self.defter_daily_date.get_date().strftime("%Y-%m-%d")
        cashier_id = self._get_defter_daily_cashier_id()

        _run_ui_background(
            self,
            self.app,
            "defter_daily_pdf",
            lambda: self.app.create_defter_daily_pdf(date_str, cashier_id),
            lambda path: messagebox.showinfo("PDF", f"DEFTER günlük raporu oluşturuldu:\n{path}", parent=self),
            "Hata",
        )

    def _pdf_defter_balance(self):
        """Generate PDF for DEFTER balance report."""
        cashier_id = self._get_defter_balance_cashier_id()

        _run_ui_background(
            self,
            self.app,
            "defter_balance_pdf",
            lambda: self.app.create_defter_balance_pdf(cashier_id),
            lambda path: messagebox.showinfo("PDF", f"DEFTER bakiye özeti oluşturuldu:\n{path}", parent=self),
            "Hata",
        )

    def on_show(self):
        self._highlight_sidebar(self.active_sidebar_key)
        if self.active_sidebar_key == "kasalar":
            self._refresh_kasa_cards()
        elif self.active_sidebar_key == "defter_daily":
            self._refresh_defter_daily_cashier_list()
            self._show_defter_daily_report()
        elif self.active_sidebar_key == "defter_balance":
            self._refresh_defter_balance_cashier_list()
            self._show_defter_balance_report()


class CustomerFormDialog(ctk.CTkToplevel):
    """Customer edit dialog with password protection for security."""

    def __init__(self, parent, app, customer: dict | None, on_save, on_delete=None, user=None):
        super().__init__(parent)
        self.on_save = on_save
        self.on_delete = on_delete
        self.user = user
        self.is_admin = user and user.get("user_type") == "admin"
        self.customer = customer
        self.app = app
        t = app.theme
        self.title("Müşteri" if customer else "Yeni Müşteri")
        self.geometry("440x450")
        _style_glass_toplevel(self, t)
        # Keep window on top
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.lift()
        self.focus_force()
        # Set window icon
        self.after(100, self._set_icon)
        c = customer or {}

        # Variables
        self.v_name = ctk.StringVar(value=c.get("name", ""))
        self.v_phone = ctk.StringVar(value=c.get("phone", ""))
        self.v_avatar = ctk.StringVar(value=c.get("avatar", ""))
        self.v_bal = ctk.StringVar(value=str(c.get("balance", 0)))
        self.v_lim = ctk.StringVar(value=str(c.get("credit_limit", -150)))
        self.v_note = ctk.StringVar(value=c.get("note", ""))

        ctk.CTkLabel(self, text="Ad", text_color=t["muted"]).pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkEntry(self, textvariable=self.v_name, width=380, **_entry_kwargs(t)).pack(padx=20)
        ctk.CTkLabel(self, text="Telefon", text_color=t["muted"]).pack(anchor="w", padx=20)
        ctk.CTkEntry(self, textvariable=self.v_phone, width=380, **_entry_kwargs(t)).pack(padx=20)
        ctk.CTkLabel(self, text="Avatar (kısaltma)", text_color=t["muted"]).pack(anchor="w", padx=20)
        ctk.CTkEntry(self, textvariable=self.v_avatar, width=380, **_entry_kwargs(t)).pack(padx=20)
        ctk.CTkLabel(self, text="Bakiye / Limit", text_color=t["muted"]).pack(anchor="w", padx=20)
        r = ctk.CTkFrame(self, fg_color="transparent")
        r.pack(anchor="w", padx=20)
        ctk.CTkEntry(r, textvariable=self.v_bal, width=180, **_entry_kwargs(t)).pack(side="left", padx=(0, 8))
        ctk.CTkEntry(r, textvariable=self.v_lim, width=180, **_entry_kwargs(t)).pack(side="left")
        ctk.CTkLabel(self, text="Not", text_color=t["muted"]).pack(anchor="w", padx=20)
        ctk.CTkEntry(self, textvariable=self.v_note, width=380, **_entry_kwargs(t)).pack(padx=20)

        # Button row
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=20)

        # Save button
        ctk.CTkButton(btn_frame, text="Kaydet", fg_color=t["accent"], command=self._ok).pack(side="left", padx=(0, 8))

        # Delete button (only for existing customers)
        if customer and on_delete:
            ctk.CTkButton(btn_frame, text="Sil", fg_color=t["danger"], hover_color="#991b1b",
                         command=self._delete).pack(side="left")
        bind_enter_action(self, self._ok, "Müşteri")

    def _set_icon(self):
        """Set window icon if available."""
        if hasattr(self.app, 'window_icon_path') and self.app.window_icon_path:
            try:
                self.iconbitmap(self.app.window_icon_path)
            except Exception:
                pass

    def _check_password(self):
        """Check password based on user type. Admin: from settings (default: 1234), Cashier: own password."""
        # Ensure this dialog stays on top before showing password dialog
        self.lift()
        self.focus_force()
        self.update()

        # Both admin and cashier use the same customer operation password
        customer_password = self.app.db.get_setting("customer_operation_password", "1234")
        pwd = simpledialog.askstring("Güvenlik", "Müşteri işlem şifresini girin:", show="*", parent=self)
        return pwd == customer_password

    def _ok(self):
        # Require password for editing existing customer
        if self.customer:
            if not self._check_password():
                messagebox.showerror("Hata", "Şifre yanlış!")
                return
            # For admin: just confirm; for cashier: already checked password
            if self.is_admin:
                if not messagebox.askyesno("Onay", f"{self.customer.get('name', '')} güncellenecek. Emin misiniz?"):
                    return
        try:
            payload = {
                "name": self.v_name.get().strip(),
                "phone": self.v_phone.get().strip(),
                "avatar": self.v_avatar.get().strip(),
                "balance": float(self.v_bal.get()),
                "credit_limit": float(self.v_lim.get()),
                "note": self.v_note.get().strip(),
            }
        except ValueError:
            messagebox.showerror("Hata", "Sayısal alanları kontrol edin.")
            return
        if not payload["name"]:
            return
        self.on_save(payload)
        self.destroy()

    def _delete(self):
        if not self.customer or not self.on_delete:
            return

        # Always require password for delete
        if not self._check_password():
            messagebox.showerror("Hata", "Şifre yanlış!")
            return

        # Confirm deletion
        if not messagebox.askyesno("Onay", f"{self.customer.get('name', '')} silinecek. Emin misiniz?"):
            return

        self.on_delete(self.customer)
        self.destroy()


class ProductEditDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, product: dict | None, on_save):
        super().__init__(parent)
        self.on_save = on_save
        self.app = app
        self.product = product or {}
        t = app.theme
        p = self.product
        self.title("Ürün")
        self.geometry("480x520")
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.lift()
        self.focus_force()
        self.after(100, self._set_icon)
        self.v_id = ctk.StringVar(value=str(p.get("id", "")) if product else "")
        self.v_name = ctk.StringVar(value=p.get("name", ""))

        self.v_cat = ctk.StringVar(value=p.get("category", "Su"))
        self.v_price = ctk.StringVar(value=str(p.get("price", 0)))
        self.v_stock = ctk.StringVar(value=str(p.get("stock", 0)))
        self.v_act = ctk.IntVar(value=p.get("active", 1))
        self.v_icon = ctk.StringVar(value=p.get("icon", ""))

        # Form fields with labels
        # Product ID is read-only; SQLite assigns it for new products.
        id_frame = ctk.CTkFrame(self, fg_color="transparent")
        id_frame.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(id_frame, text="ID:", text_color=t["text"], font=ctk.CTkFont(size=12, weight="bold"), width=80).pack(side="left")
        ctk.CTkEntry(id_frame, textvariable=self.v_id, placeholder_text="Otomatik", width=300, state="disabled", **_entry_kwargs(t)).pack(side="left")
        
        # Product Name
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(name_frame, text="Ürün İsmi:", text_color=t["text"], font=ctk.CTkFont(size=12, weight="bold"), width=80).pack(side="left")
        ctk.CTkEntry(name_frame, textvariable=self.v_name, placeholder_text="Ürün adını girin", width=300, **_entry_kwargs(t)).pack(side="left")
        
        # Category
        cat_frame = ctk.CTkFrame(self, fg_color="transparent")
        cat_frame.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(cat_frame, text="Kategori:", text_color=t["text"], font=ctk.CTkFont(size=12, weight="bold"), width=80).pack(side="left")
        ctk.CTkEntry(cat_frame, textvariable=self.v_cat, placeholder_text="Kategori girin", width=300, **_entry_kwargs(t)).pack(side="left")
        
        # Price
        price_frame = ctk.CTkFrame(self, fg_color="transparent")
        price_frame.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(price_frame, text="Fiyat (TL):", text_color=t["text"], font=ctk.CTkFont(size=12, weight="bold"), width=80).pack(side="left")
        ctk.CTkEntry(price_frame, textvariable=self.v_price, placeholder_text="Fiyatı girin", width=300, **_entry_kwargs(t)).pack(side="left")
        
        # Stock
        stock_frame = ctk.CTkFrame(self, fg_color="transparent")
        stock_frame.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(stock_frame, text="Stok:", text_color=t["text"], font=ctk.CTkFont(size=12, weight="bold"), width=80).pack(side="left")
        ctk.CTkEntry(stock_frame, textvariable=self.v_stock, placeholder_text="Stok miktarını girin", width=300, **_entry_kwargs(t)).pack(side="left")
        
        # Active Status
        active_frame = ctk.CTkFrame(self, fg_color="transparent")
        active_frame.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(active_frame, text="Durum:", text_color=t["text"], font=ctk.CTkFont(size=12, weight="bold"), width=80).pack(side="left")
        ctk.CTkCheckBox(active_frame, text="Aktif", variable=self.v_act, fg_color=t["accent"]).pack(side="left")
        
        # Icon selector button
        icon_frame = ctk.CTkFrame(self, fg_color="transparent")
        icon_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(icon_frame, text="İkon: ", text_color=t["text"], font=ctk.CTkFont(size=14)).pack(side="left")
        self.icon_preview = ctk.CTkLabel(icon_frame, text=self.v_icon.get() or "🛍️", font=ctk.CTkFont(size=24), width=40)
        self.icon_preview.pack(side="left", padx=10)
        ctk.CTkButton(
            icon_frame,
            text="İkon Seç",
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            command=self._pick_icon,
        ).pack(side="left", padx=10)
        
        # Button row
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=16)

        ctk.CTkButton(btn_frame, text="Kaydet", fg_color=t["accent"], hover_color=t["accent_hover"], command=self._ok).pack(side="left", padx=(0, 8))

        # Delete button for existing products
        if self.product and self.product.get("id"):
            ctk.CTkButton(btn_frame, text="Sil", fg_color=t["danger"], hover_color="#991b1b",
                         command=self._delete).pack(side="left")
        bind_enter_action(self, self._ok, "Ürün")

    def _delete(self):
        """Delete the product with ownership verification."""
        if self.product.get("_edit_cashier_id") is not None and int(self.product.get("cashier_id", 0)) == 0:
            messagebox.showwarning("Ürün", "Ortak Ürün silinemez. Bu Ürünu düzenlerseniz kasaya özel kopya olusturulur.")
            return
        if not messagebox.askyesno("Onay", "Bu ürün pasifleştirilsin mi?"):
            return
        try:
            self.on_save({"deleted": True, "id": self.product["id"]})
        except ValueError as e:
            messagebox.showerror("Hata", str(e))
            return
        self.destroy()

    def _pick_icon(self):
        IconPickerDialog(self, self.app.theme, self.v_icon, self.icon_preview)

    def _set_icon(self):
        """Set window icon if available."""
        if hasattr(self.app, 'window_icon_path') and self.app.window_icon_path:
            try:
                self.iconbitmap(self.app.window_icon_path)
            except Exception:
                pass

    def _ok(self):
        try:
            name = self.v_name.get().strip()
            category = self.v_cat.get().strip()
            if not name:
                messagebox.showerror("Hata", "Ürün adı zorunlu.")
                return
            if not category:
                messagebox.showerror("Hata", "Kategori zorunlu.")
                return
            price = float(self.v_price.get().replace(",", "."))
            stock = float(self.v_stock.get().replace(",", "."))
            if price < 0:
                messagebox.showerror("Hata", "Fiyat negatif olamaz.")
                return
            if stock < 0:
                messagebox.showerror("Hata", "Stok negatif olamaz.")
                return
            d = {
                "name": name,
                "category": category,
                "price": price,
                "stock": stock,
                "active": int(self.v_act.get()),
                "icon": self.v_icon.get(),
            }
        except ValueError:
            messagebox.showerror("Hata", "Fiyat ve stok alanlarına geçerli sayı girin.")
            return
        try:
            self.on_save(d)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Hata", f"Ürün kaydedilirken hata: {str(e)}")


class IconPickerDialog(ctk.CTkToplevel):
    """Emoji icon picker for products - organized by categories with food icons."""
    
    ICON_CATEGORIES = {
        "Icecekler": ["💧", "💦", "☕", "🍵", "🥤", "🧃", "🧉", "🍺", "🍷", "🥛", "🫗", "🧊"],
        "Kahveler": ["☕", "🫘", "🥄", "🍮", "🧋"],
        "Takviyeler": ["💪", "💊", "🧬", "🏋️", "⚡", "🔥", "⚗️", "🧪", "🩺", "❤️", "🐟"],
        "Yiyecekler": ["🍫", "🍩", "🍪", "🥜", "🍿", "🥗", "🥪", "🌯", "🍞", "🥐", "🥯", "🧀", "🍖", "🍗", "🥩", "🥓", "🍳", "🥚", "🧇", "🥞"],
        "Meyveler": ["🍎", "🍌", "🍊", "🍇", "🍓", "🫐", "🍈", "🍉", "🍒", "🍑", "🥭", "🍍", "🥝", "🍋", "🍐"],
        "Genel": ["🛍️", "🎁", "✨", "⭐", "🔔", "📦", "🏷️", "💰", "💳", "🎉", "👕", "👟", "🎽", "🧘", "🧴", "🧼", "🪞"],
    }
    
    def __init__(self, parent, theme: dict, icon_var, preview_label):
        super().__init__(parent)
        self.icon_var = icon_var
        self.preview_label = preview_label
        t = theme
        self.title("Ikon Sec")
        self.geometry("600x500")
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.lift()
        self.focus_force()
        
        # Title
        ctk.CTkLabel(
            self,
            text="Ürün İkonu Seç",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=t["text"]
        ).pack(pady=(20, 10))
        
        # Current selection display
        current_frame = ctk.CTkFrame(self, fg_color=t["panel"], corner_radius=10)
        current_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(current_frame, text="Secili: ", text_color=t["muted"], font=ctk.CTkFont(size=14)).pack(side="left", padx=15, pady=10)
        self.current_preview = ctk.CTkLabel(current_frame, text=icon_var.get() or "🛍️", font=ctk.CTkFont(size=32), width=50)
        self.current_preview.pack(side="left", padx=5)
        
        # Category tabs
        self.tab_view = ctk.CTkTabview(self, fg_color=t["panel"], segmented_button_fg_color=t["panel2"],
                                       segmented_button_selected_color=t["accent"],
                                       segmented_button_selected_hover_color=t["accent_hover"],
                                       text_color=t["text"])
        self.tab_view.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Create tabs for each category
        for category, icons in self.ICON_CATEGORIES.items():
            tab = self.tab_view.add(category)
            self._create_icon_grid(tab, icons, t)
        
        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 15))
        ctk.CTkButton(
            btn_frame,
            text="Temizle (Varsayilan)",
            fg_color=t["panel2"],
            hover_color=t["border"],
            command=self._clear_icon,
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            btn_frame,
            text="Kapat",
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            command=self.destroy,
        ).pack(side="right", padx=5)
    
    def _create_icon_grid(self, parent, icons, theme):
        """Create a grid of icon buttons."""
        grid_frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        cols = 6
        for i, icon in enumerate(icons):
            btn = ctk.CTkButton(
                grid_frame,
                text=icon,
                font=ctk.CTkFont(size=28),
                width=60,
                height=60,
                fg_color=theme["panel2"],
                hover_color=theme["accent"],
                text_color="white",
                corner_radius=8,
                command=lambda ic=icon: self._select_icon(ic),
            )
            btn.grid(row=i // cols, column=i % cols, padx=5, pady=5)
    
    def _select_icon(self, icon):
        """Select an icon and update the variable."""
        self.icon_var.set(icon)
        self.current_preview.configure(text=icon)
        if self.preview_label:
            self.preview_label.configure(text=icon)
    
    def _clear_icon(self):
        """Clear the icon selection (use default)."""
        self.icon_var.set("")
        self.current_preview.configure(text="🛍️")
        if self.preview_label:
            self.preview_label.configure(text="🛍️")


class CashPayDialog(ctk.CTkToplevel):
    def __init__(self, parent, theme: dict, total: float, on_ok):
        super().__init__(parent)
        self.on_ok = on_ok
        t = theme
        self.title("Nakit")
        self.geometry("320x200")
        _style_glass_toplevel(self, t)
        # Keep window on top
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.lift()
        self.focus_force()
        ctk.CTkLabel(self, text=f"Toplam: {money(total)}", font=ctk.CTkFont(size=16, weight="bold"), text_color=t["text"]).pack(pady=16)
        ctk.CTkButton(self, text="Onayla", fg_color=t["success"], hover_color="#22c55e", command=lambda: (on_ok(), self.destroy())).pack(pady=12)


class PayConfirmDialog(ctk.CTkToplevel):
    def __init__(self, parent, theme: dict, title: str, total: float, on_ok):
        super().__init__(parent)
        t = theme
        self.title(title)
        self.geometry("340x210")
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.lift()
        self.focus_force()
        ctk.CTkLabel(self, text=f"{title} odemesi", font=ctk.CTkFont(size=18, weight="bold"), text_color=t["text"]).pack(pady=(22, 8))
        ctk.CTkLabel(self, text=f"Toplam: {money(total)}", font=ctk.CTkFont(size=16, weight="bold"), text_color=t["text"]).pack(pady=6)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=16)
        ctk.CTkButton(row, text="Iptal", width=100, fg_color=t["panel2"], text_color=t["text"], command=self.destroy).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Onayla", width=120, fg_color=t["success"], hover_color="#22c55e", command=lambda: (on_ok(), self.destroy())).pack(side="left", padx=6)


class DefterPickerDialog(ctk.CTkToplevel):
    PAGE_SIZE = 40
    RENDER_BATCH_SIZE = 10

    @measure("dashboard_render_suresi", lambda self, parent, app, on_pick, user=None: "DefterPickerDialog")
    def __init__(self, parent, app, on_pick, user=None):
        super().__init__(parent)
        self.app = app
        self.on_pick = on_pick
        self.user = user
        self.cashier_id = user["id"] if user and user.get("user_type") == "cashier" else None
        t = app.theme
        self.title("Defter — Musteri")
        self.title("Defter - Musteri")
        self.geometry("760x680")
        self.minsize(680, 560)
        _style_glass_toplevel(self, t)
        # Keep window on top
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.lift()
        self.focus_force()
        self.letter = ""
        self._render_after_id = None
        self._render_token = 0
        self._loading = False
        self._pending_picker_render = False
        self._closed = False
        self._all_customers = []
        self._visible_count = 0
        self._letter_buttons = {}
        self.search_var = ctk.StringVar()
        search = ctk.CTkEntry(self, textvariable=self.search_var, placeholder_text="Musteri ara...", **_entry_kwargs(t))
        search.pack(fill="x", padx=10, pady=(12, 4))
        search.bind("<KeyRelease>", lambda _e: self._schedule_render())
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(4, 10))
        self._all_button = ctk.CTkButton(
            top,
            text="Tumu",
            width=68,
            height=32,
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._set_letter(""),
        )
        self._all_button.grid(row=0, column=0, padx=3, pady=3)
        for i, L in enumerate(string.ascii_uppercase):
            btn = ctk.CTkButton(
                top,
                text=L,
                width=36,
                height=32,
                fg_color=t.get("input", t["panel2"]),
                hover_color=t["accent_hover"],
                text_color=t["text"],
                border_width=1,
                border_color=t["border"],
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda x=L: self._set_letter(x),
            )
            btn.grid(row=(i + 1) // 13, column=(i + 1) % 13, padx=3, pady=3)
            self._letter_buttons[L] = btn
        self.list_fr = ctk.CTkScrollableFrame(self, fg_color=t["panel"])
        self.list_fr.pack(fill="both", expand=True, padx=10, pady=10)
        self._set_letter_button_state()
        self.after(40, self._render)

    def _set_letter(self, L):
        self.letter = L
        self._set_letter_button_state()
        self._schedule_render()

    def _set_letter_button_state(self):
        t = self.app.theme
        all_active = self.letter == ""
        self._all_button.configure(
            fg_color=t["accent"] if all_active else t.get("input", t["panel2"]),
            text_color="#FFFFFF" if all_active else t["text"],
            border_color=t["accent"] if all_active else t["border"],
        )
        for letter, btn in self._letter_buttons.items():
            active = self.letter == letter
            btn.configure(
                fg_color=t["accent"] if active else t.get("input", t["panel2"]),
                text_color="#FFFFFF" if active else t["text"],
                border_color=t["accent"] if active else t["border"],
            )

    def _schedule_render(self):
        if self._render_after_id:
            try:
                self.after_cancel(self._render_after_id)
            except Exception:
                pass
        self._render_after_id = self.after(220, self._render)

    def _safe_exists(self) -> bool:
        return not self._closed and bool(self.winfo_exists())

    @measure("musteri_arama_suresi", lambda self: f"DefterPicker letter={getattr(self, 'letter', '')}")
    def _render(self):
        if not self._safe_exists():
            return
        if self._loading:
            self._pending_picker_render = True
            return
        self._loading = True
        self._render_token += 1
        token = self._render_token
        for w in self.list_fr.winfo_children():
            w.destroy()
        t = self.app.theme
        ctk.CTkLabel(self.list_fr, text="Müşteriler yükleniyor...", text_color=t["muted"]).pack(pady=24)
        search_text = self.search_var.get().strip()

        def work():
            if search_text:
                return self.app.db.list_customers(search_text, cashier_id=self.cashier_id)
            if self.letter:
                return self.app.db.list_customers_startswith(self.letter, cashier_id=self.cashier_id)
            return self.app.db.list_customers("", cashier_id=self.cashier_id)

        def done(customers):
            if not self._safe_exists() or token != self._render_token:
                return
            self._loading = False
            if self._pending_picker_render:
                self._pending_picker_render = False
                self._schedule_render()
                return
            self._all_customers = list(customers or [])
            self._visible_count = 0
            for w in self.list_fr.winfo_children():
                w.destroy()
            if not self._all_customers:
                ctk.CTkLabel(self.list_fr, text="Müşteri bulunamadı", text_color=t["muted"]).pack(pady=24)
                return
            self._render_next_page(token)

        def failed(exc):
            if not self._safe_exists() or token != self._render_token:
                return
            self._loading = False
            if self._pending_picker_render:
                self._pending_picker_render = False
                self._schedule_render()
                return
            for w in self.list_fr.winfo_children():
                w.destroy()
            ctk.CTkLabel(self.list_fr, text=f"Müşteri listesi okunamadı: {exc}", text_color=t["danger"], wraplength=620).pack(pady=24, padx=16)

        self.app.run_background_io("defter_customer_load", work, done, failed)

    def _render_next_page(self, token=None):
        if not self._safe_exists():
            return
        token = self._render_token if token is None else token
        for child in self.list_fr.winfo_children():
            if getattr(child, "_is_more_button", False):
                child.destroy()
        start = self._visible_count
        end = min(len(self._all_customers), start + self.PAGE_SIZE)
        self._render_customer_batch(start, end, token)

    def _render_customer_batch(self, index: int, end: int, token: int):
        if not self._safe_exists() or token != self._render_token:
            return
        batch_end = min(end, index + self.RENDER_BATCH_SIZE)
        for c in self._all_customers[index:batch_end]:
            self._add_customer_row(c)
        self._visible_count = batch_end
        if batch_end < end:
            self.after(1, lambda: self._render_customer_batch(batch_end, end, token))
            return
        if self._visible_count < len(self._all_customers):
            self._add_more_button()

    def _add_customer_row(self, c: dict):
        t = self.app.theme
        try:
            row = ctk.CTkFrame(self.list_fr, fg_color=t["panel2"], corner_radius=8)
            row.pack(fill="x", pady=5)
            ctk.CTkLabel(row, text=f"{c['name']} - {money(c['balance'])}", text_color=t["text"]).pack(side="left", padx=10, pady=8)
            ctk.CTkButton(
                row,
                text="Sec",
                width=80,
                fg_color=t["accent"],
                hover_color=t["accent_hover"],
                command=lambda x=c: self._choose(x),
            ).pack(side="right", padx=8)
        except Exception as exc:
            print(f"Defter customer row skipped: {exc}")

    def _add_more_button(self):
        t = self.app.theme
        btn = ctk.CTkButton(
            self.list_fr,
            text=f"Daha fazla göster ({self._visible_count}/{len(self._all_customers)})",
            fg_color=t["panel2"],
            hover_color=t["accent_hover"],
            text_color=t["text"],
            command=lambda: self._render_next_page(self._render_token),
        )
        btn._is_more_button = True
        btn.pack(fill="x", pady=10, padx=6)

    def _choose(self, c):
        self.on_pick(c)
        self.destroy()

    def destroy(self):
        self._closed = True
        if self._render_after_id:
            try:
                self.after_cancel(self._render_after_id)
            except Exception:
                pass
        super().destroy()


class CustomerBalanceStatusDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, db, cashier_id: int | None, username: str | None = None):
        super().__init__(parent)
        self.app = app
        self.db = db
        self.cashier_id = cashier_id
        self.username = username
        self.customers = []
        t = app.theme
        self.title("Müşteri Bakiye Durumu")
        self.geometry("620x620")
        self.minsize(520, 460)
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.lift()
        self.focus_force()

        header = ctk.CTkFrame(self, fg_color=t["panel"], corner_radius=12, border_width=1, border_color=t["border"])
        header.pack(fill="x", padx=14, pady=(14, 8))
        title = "Müşteri Bakiye Durumu"
        if username:
            title = f"{title} - {username}"
        ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=18, weight="bold"), text_color=t["text"]).pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(header, text="Ad Soyad — Bakiye", font=ctk.CTkFont(size=12), text_color=t["muted"]).pack(anchor="w", padx=16, pady=(0, 12))
        ctk.CTkButton(
            header,
            text="PDF Oluştur/Yazdır",
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            command=self._create_pdf,
        ).pack(anchor="e", padx=16, pady=(0, 12))

        self.list_fr = ctk.CTkScrollableFrame(self, fg_color=t["bg"])
        self.list_fr.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._load_customers()
        self._render()

    @measure("musteri_verisi_yukleme_suresi", lambda self: "CustomerBalanceStatusDialog._load_customers")
    def _load_customers(self):
        try:
            customers = self.db.list_customers("", cashier_id=self.cashier_id, include_archived=False)
        except Exception as exc:
            messagebox.showerror("Hata", f"Müşteri bakiyeleri alınırken hata:\n{exc}")
            self.destroy()
            return
        self.customers = sorted(customers, key=lambda row: str(row.get("name", "")).casefold())

    @measure("dashboard_render_suresi", lambda self: "CustomerBalanceStatusDialog._render")
    def _render(self):
        t = self.app.theme
        for widget in self.list_fr.winfo_children():
            widget.destroy()
        if not self.customers:
            ctk.CTkLabel(self.list_fr, text="Müşteri bulunamadı", text_color=t["muted"], font=ctk.CTkFont(size=14)).pack(pady=28)
            return
        for customer in self.customers:
            balance = float(customer.get("balance", 0) or 0)
            if balance > 0:
                balance_color = t["success"]
            elif balance < 0:
                balance_color = t["danger"]
            else:
                balance_color = t["muted"]
            row = ctk.CTkFrame(self.list_fr, fg_color=t["panel"], corner_radius=8, border_width=1, border_color=t["border"])
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(
                row,
                text=f"{customer.get('name', '')} — {money(balance)}",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=balance_color,
                anchor="w",
            ).pack(fill="x", padx=12, pady=9)

    def _report_dir(self):
        if self.username:
            return get_kasa_reports_dir(self.username)
        return get_reports_dir()

    @measure("pdf_olusturma_suresi", lambda self: "CustomerBalanceStatusDialog._create_pdf")
    def _create_pdf(self):
        def done(path):
            should_print = messagebox.askyesno(
                "PDF Oluştur/Yazdır",
                f"PDF oluşturuldu:\n{path}\n\nYazdırmaya gönderilsin mi?",
                parent=self,
            )
            if should_print:
                try:
                    os.startfile(path, "print")
                except Exception as exc:
                    messagebox.showwarning("Yazdır", f"PDF oluşturuldu ancak yazdırma başlatılamadı:\n{exc}\n\n{path}", parent=self)

        _run_ui_background(self, self.app, "customer_balance_pdf", self._write_pdf, done, "Hata")

    @measure("pdf_olusturma_suresi", lambda self: "CustomerBalanceStatusDialog._write_pdf")
    def _write_pdf(self):
        from reportlab.lib.colors import HexColor, black, white
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas

        report_dir = os.path.abspath(str(self._report_dir()))
        os.makedirs(report_dir, exist_ok=True)
        now = datetime.now()
        path = os.path.join(report_dir, f"musteri_bakiye_durumu_{now.strftime('%Y-%m-%d_%H-%M-%S')}.pdf")

        total_customers = len(self.customers)
        total_debt = sum(abs(float(c.get("balance", 0) or 0)) for c in self.customers if float(c.get("balance", 0) or 0) < 0)
        total_credit = sum(float(c.get("balance", 0) or 0) for c in self.customers if float(c.get("balance", 0) or 0) > 0)
        total_balance = sum(float(c.get("balance", 0) or 0) for c in self.customers)
        profile_name = self.username or "Yönetici"

        pdf = canvas.Canvas(path, pagesize=A4)
        regular_font, bold_font, _italic_font = get_pdf_fonts(getattr(self.app, "base_dir", None))
        width, height = A4
        margin = 1.4 * cm
        y = height - margin

        pdf.setTitle("Müşteri Bakiye Durumu")
        pdf.setAuthor("MatadorsApp")
        pdf.setFillColor(HexColor("#111827"))
        pdf.setFont(bold_font, 18)
        pdf.drawString(margin, y, "Müşteri Bakiye Durumu")
        y -= 0.65 * cm

        pdf.setFont(regular_font, 10)
        pdf.setFillColor(HexColor("#374151"))
        pdf.drawString(margin, y, f"Tarih-Saat: {now.strftime('%d.%m.%Y %H:%M')}")
        y -= 0.45 * cm
        pdf.drawString(margin, y, f"Kasa/Profil: {profile_name}")
        y -= 0.65 * cm

        pdf.setFillColor(HexColor("#E5E7EB"))
        pdf.rect(margin, y - 0.5 * cm, width - (2 * margin), 0.75 * cm, fill=1, stroke=0)
        pdf.setFillColor(HexColor("#111827"))
        pdf.setFont(bold_font, 9)
        summary = (
            f"Toplam Müşteri: {total_customers}   "
            f"Toplam Borç: {money(total_debt)}   "
            f"Toplam Alacak: {money(total_credit)}   "
            f"Toplam Bakiye: {money(total_balance)}"
        )
        pdf.drawString(margin + 0.25 * cm, y - 0.22 * cm, summary)
        y -= 1.05 * cm

        def draw_header():
            nonlocal y
            pdf.setFillColor(HexColor("#111827"))
            pdf.rect(margin, y - 0.45 * cm, width - (2 * margin), 0.6 * cm, fill=1, stroke=0)
            pdf.setFillColor(white)
            pdf.setFont(bold_font, 10)
            pdf.drawString(margin + 0.25 * cm, y - 0.2 * cm, "Ad Soyad")
            pdf.drawRightString(width - margin - 0.25 * cm, y - 0.2 * cm, "Bakiye")
            y -= 0.7 * cm

        draw_header()
        pdf.setFont(regular_font, 10)
        for customer in self.customers:
            if y < margin + 0.8 * cm:
                pdf.showPage()
                y = height - margin
                draw_header()
                pdf.setFont(regular_font, 10)
            balance = float(customer.get("balance", 0) or 0)
            if balance > 0:
                color = HexColor("#16A34A")
            elif balance < 0:
                color = HexColor("#E30613")
            else:
                color = HexColor("#6B7280")
            pdf.setFillColor(black)
            pdf.drawString(margin + 0.25 * cm, y, str(customer.get("name", ""))[:70])
            pdf.setFillColor(color)
            pdf.drawRightString(width - margin - 0.25 * cm, y, money(balance))
            y -= 0.42 * cm

        pdf.save()
        return path


class ExpenseDialog(ctk.CTkToplevel):
    """Dialog for adding other expenses."""

    def __init__(self, parent, app, user: dict):
        super().__init__(parent)
        self.app = app
        self.user = user
        self.cashier_id = user["id"]
        t = app.theme

        self.title("Diğer Giderler")
        self.geometry("500x500")
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.lift()
        self.focus_force()
        self.after(100, self._set_icon)

        # Header
        ctk.CTkLabel(
            self,
            text="Diğer Giderler",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=t["text"],
        ).pack(pady=(20, 10))

        # Form frame
        form_frame = ctk.CTkFrame(self, fg_color="transparent")
        form_frame.pack(fill="x", padx=20, pady=10)

        # Expense name
        ctk.CTkLabel(form_frame, text="Gider Adı", text_color=t["muted"]).pack(anchor="w")
        self.v_name = ctk.StringVar()
        ctk.CTkEntry(form_frame, textvariable=self.v_name, width=400, **_entry_kwargs(t)).pack(fill="x", pady=(0, 10))

        # Expense amount
        ctk.CTkLabel(form_frame, text="Tutar (TL)", text_color=t["muted"]).pack(anchor="w")
        self.v_amount = ctk.StringVar()
        ctk.CTkEntry(form_frame, textvariable=self.v_amount, width=400, **_entry_kwargs(t)).pack(fill="x", pady=(0, 10))

        # Expense note
        ctk.CTkLabel(form_frame, text="Not", text_color=t["muted"]).pack(anchor="w")
        self.v_note = ctk.StringVar()
        ctk.CTkEntry(form_frame, textvariable=self.v_note, width=400, **_entry_kwargs(t)).pack(fill="x", pady=(0, 10))

        # Add button with absolute error prevention
        def safe_add_expense():
            try:
                # Maximum safety approach
                name = ""
                amount_str = ""
                note = ""
                
                # Get values with maximum safety
                try:
                    name = str(self.v_name.get()).strip()
                except:
                    name = ""
                
                try:
                    amount_str = str(self.v_amount.get()).strip()
                except:
                    amount_str = ""
                
                try:
                    note = str(self.v_note.get()).strip()
                except:
                    note = ""
                
                # Basic validation
                if not name:
                    messagebox.showerror("Hata", "Gider adı zorunlu.")
                    return
                
                # Amount validation
                try:
                    amount = float(amount_str)
                    if amount <= 0:
                        messagebox.showerror("Hata", "Geçerli bir tutar girin.")
                        return
                except:
                    messagebox.showerror("Hata", "Geçerli bir tutar girin.")
                    return
                
                # Database operation with safety
                try:
                    self.app.db.add_expense(name, amount, note, self.cashier_id)
                    
                    # Clear form safely
                    try:
                        self.v_name.set("")
                    except:
                        pass
                    try:
                        self.v_amount.set("")
                    except:
                        pass
                    try:
                        self.v_note.set("")
                    except:
                        pass
                    
                    # Refresh list safely
                    try:
                        self._refresh_list()
                    except:
                        pass
                    
                    # Success message
                    messagebox.showinfo("Başarılı", "Gider eklendi.")
                    
                except Exception as db_error:
                    messagebox.showerror("Hata", f"Veritabanı hatası: {str(db_error)}")
                    
            except Exception as e:
                messagebox.showerror("Hata", f"Gider eklenirken hata: {str(e)}")
        
        ctk.CTkButton(
            form_frame,
            text="Gider Ekle",
            fg_color=t["danger"],
            hover_color="#991b1b",
            command=safe_add_expense,
        ).pack(fill="x", pady=(10, 0))

        # List header
        ctk.CTkLabel(
            self,
            text="Bugünkü Giderler",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=t["text"],
        ).pack(pady=(20, 10))

        # Expenses list
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=t["panel"], height=200)
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self._refresh_list()

    def _set_icon(self):
        """Set window icon if available."""
        if hasattr(self.app, 'window_icon_path') and self.app.window_icon_path:
            try:
                self.iconbitmap(self.app.window_icon_path)
            except Exception:
                pass

    def _add_expense(self):
        """Add new expense - ABSOLUTE ERROR PREVENTION."""
        try:
            # MAXIMUM SAFETY - Get values with individual error handling
            name = ""
            amount_str = ""
            note = ""
            
            try:
                if hasattr(self, 'v_name') and self.v_name:
                    name = str(self.v_name.get()).strip()
            except:
                name = ""
            
            try:
                if hasattr(self, 'v_amount') and self.v_amount:
                    amount_str = str(self.v_amount.get()).strip()
            except:
                amount_str = ""
            
            try:
                if hasattr(self, 'v_note') and self.v_note:
                    note = str(self.v_note.get()).strip()
            except:
                note = ""

            # Basic validation with safety
            if not name:
                try:
                    messagebox.showerror("Hata", "Gider adı zorunlu.")
                except:
                    print("Hata: Gider adı zorunlu.")
                return

            # Amount validation with maximum safety
            try:
                amount = float(amount_str)
                if amount <= 0:
                    try:
                        messagebox.showerror("Hata", "Geçerli bir tutar girin.")
                    except:
                        print("Hata: Geçerli bir tutar girin.")
                    return
            except (ValueError, TypeError):
                try:
                    messagebox.showerror("Hata", "Geçerli bir tutar girin.")
                except:
                    print("Hata: Geçerli bir tutar girin.")
                return

            # Database operation with comprehensive safety
            try:
                if hasattr(self, 'app') and hasattr(self.app, 'db') and self.app.db:
                    self.app.db.add_expense(name, amount, note, self.cashier_id)
                else:
                    try:
                        messagebox.showerror("Hata", "Veritabanı bağlantısı yok.")
                    except:
                        print("Hata: Veritabanı bağlantısı yok.")
                    return
            except Exception as db_error:
                try:
                    messagebox.showerror("Hata", f"Veritabanı hatası: {str(db_error)}")
                except:
                    print(f"Veritabanı hatası: {db_error}")
                return
            
            # Clear form with individual safety
            try:
                if hasattr(self, 'v_name') and self.v_name:
                    self.v_name.set("")
            except:
                pass
            
            try:
                if hasattr(self, 'v_amount') and self.v_amount:
                    self.v_amount.set("")
            except:
                pass
            
            try:
                if hasattr(self, 'v_note') and self.v_note:
                    self.v_note.set("")
            except:
                pass
            
            # Refresh list with safety
            try:
                if hasattr(self, '_refresh_list'):
                    self._refresh_list()
            except:
                print("Warning: List refresh failed")
            
            # Success message with fallback
            try:
                messagebox.showinfo("Başarılı", "Gider eklendi.")
            except:
                print("Başarılı: Gider eklendi.")
            
        except Exception as e:
            # Ultimate fallback error handling
            try:
                messagebox.showerror("Hata", f"Gider eklenirken hata: {str(e)}")
            except:
                print(f"Gider eklenirken hata: {e}")
                print("Lütfen programı yeniden başlatın.")

    @measure("dashboard_render_suresi", lambda self: "ExpenseDialog._refresh_list")
    def _refresh_list(self):
        """Refresh expenses list with comprehensive error handling."""
        try:
            # Clear existing widgets safely
            try:
                for widget in self.list_frame.winfo_children():
                    widget.destroy()
            except:
                pass  # Continue even if widget clearing fails

            # Get theme and date safely
            t = getattr(self.app, 'theme', {})
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Get expenses from database safely
            expenses = []
            try:
                if hasattr(self.app, 'db') and self.app.db:
                    expenses = self.app.db.list_expenses(cashier_id=self.cashier_id, date_str=today)
            except:
                pass  # Continue with empty list if database fails

            # Show empty message if no expenses
            if not expenses:
                try:
                    ctk.CTkLabel(
                        self.list_frame,
                        text="Bugün henüz gider eklenmemiş.",
                        text_color=t.get("muted", "#888888"),
                    ).pack(pady=20)
                except:
                    print("Bugün henüz gider eklenmemiş.")
                return

            # Calculate total safely
            total = 0.0
            for exp in expenses:
                try:
                    amount = float(exp.get("amount", 0))
                    total += amount
                except (ValueError, TypeError):
                    continue  # Skip invalid amounts

            # Create expense rows safely
            for exp in expenses:
                try:
                    # Expense row
                    row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
                    row.pack(fill="x", pady=2)

                    # Info
                    info = ctk.CTkFrame(row, fg_color="transparent")
                    info.pack(side="left", fill="x", expand=True)

                    ctk.CTkLabel(
                        info,
                        text=exp.get("name", ""),
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=t.get("text", "#000000"),
                    ).pack(anchor="w")

                    note_text = f" - {exp.get('note', '')}" if exp.get("note") else ""
                    ctk.CTkLabel(
                        info,
                        text=f"{money(exp.get('amount', 0))}{note_text}",
                        text_color=t.get("muted", "#888888"),
                        font=ctk.CTkFont(size=12),
                    ).pack(anchor="w")

                    # Delete button with safe command
                    def safe_delete(expense_id=exp.get("id")):
                        try:
                            self._delete_expense(expense_id)
                        except Exception as e:
                            try:
                                messagebox.showerror("Hata", f"Gider silinirken hata: {str(e)}")
                            except:
                                print(f"Gider silme hatası: {e}")

                    ctk.CTkButton(
                        row,
                        text="Sil",
                        width=60,
                        height=24,
                        fg_color=t.get("danger", "#e74c3c"),
                        hover_color="#991b1b",
                        font=ctk.CTkFont(size=11),
                        command=safe_delete,
                    ).pack(side="right", padx=(10, 0))

                except Exception as row_error:
                    print(f"Expense row creation error: {row_error}")
                    continue  # Skip to next expense

            # Total
            try:
                ctk.CTkFrame(self.list_frame, fg_color=t.get("border", "#ddd"), height=1).pack(fill="x", pady=10)
                total_row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
                total_row.pack(fill="x")
                ctk.CTkLabel(
                    total_row,
                    text="Toplam:",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=t.get("text", "#000000"),
                ).pack(side="left")
                ctk.CTkLabel(
                    total_row,
                    text=money(total),
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=t.get("danger", "#e74c3c"),
                ).pack(side="right")
            except:
                print("Warning: Total display failed")

        except Exception as e:
            # Catch-all error handler for list refresh
            try:
                ctk.CTkLabel(
                    self.list_frame,
                    text="Liste yüklenirken hata oluştu.",
                    text_color="#e74c3c",
                ).pack(pady=20)
            except:
                print("Liste yükleme hatası:", e)

    def _delete_expense(self, expense_id: int):
        """Delete an expense with comprehensive error handling."""
        try:
            # Show confirmation dialog safely
            try:
                if not messagebox.askyesno("Onay", "Bu gideri silmek istediğinize emin misiniz?"):
                    return
            except:
                print("Onay dialogu gösterilemedi, işlem iptal edildi.")
                return

            # Delete from database safely
            try:
                if hasattr(self.app, 'db') and self.app.db:
                    self.app.db.delete_expense(expense_id, self.cashier_id)
                    self._refresh_list()
                else:
                    print("Veritabanı bağlantısı yok.")
            except Exception as db_error:
                try:
                    messagebox.showerror("Hata", f"Gider silinemedi: {str(db_error)}")
                except:
                    print(f"Gider silme hatası: {db_error}")

        except Exception as e:
            # Catch-all error handler
            try:
                messagebox.showerror("Hata", f"Beklenmedik hata: {str(e)}")
            except:
                print(f"Gider silme hatası: {e}")


class ThemeCustomizerDialog(ctk.CTkToplevel):
    """Compact theme editor used from Settings."""

    COLOR_FIELDS = [
        ("Arka Plan Rengi", "bg"),
        ("Üst Menü Rengi", "top"),
        ("Yan Menü Rengi", "sidebar"),
        ("Kart / Panel Rengi", "glass"),
        ("Panel Rengi", "panel"),
        ("İkincil Panel Rengi", "panel2"),
        ("Buton Rengi", "accent"),
        ("Buton Vurgu Rengi", "accent_hover"),
        ("Yazı Rengi", "text"),
        ("İkincil Yazı Rengi", "muted"),
        ("Çizgi Rengi", "border"),
        ("Giriş Alanı Rengi", "input"),
        ("Başarı Rengi", "success"),
        ("Uyarı Rengi", "danger"),
    ]

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.theme = DEFAULT_NEON_THEME.copy()
        self.theme.update(app.theme)
        self.vars = {}
        self.swatches = {}
        t = app.theme
        self.title("Görünüm Ayarları")
        self.geometry("920x680")
        self.minsize(820, 600)
        _style_glass_toplevel(self, t)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        root = ctk.CTkFrame(self, fg_color=t.get("glass", t["panel"]), corner_radius=18, border_width=1, border_color=t["border"])
        root.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(root, text="Görünüm Ayarları", font=ctk.CTkFont(size=26, weight="bold"), text_color=t["text"]).pack(anchor="w", padx=22, pady=(18, 4))
        ctk.CTkLabel(root, text="Renkleri, yazıları ve pencere saydamlığını buradan düzenleyin.", font=ctk.CTkFont(size=14), text_color=t["muted"]).pack(anchor="w", padx=22, pady=(0, 14))

        body = ctk.CTkFrame(root, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        form = ctk.CTkScrollableFrame(body, fg_color="transparent")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        preview = ctk.CTkFrame(body, fg_color=self.theme["glass"], corner_radius=16, border_width=1, border_color=self.theme["border"])
        preview.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.preview = preview

        for label, key in self.COLOR_FIELDS:
            self._color_row(form, label, key)

        self.window_opacity = ctk.DoubleVar(value=float(self.theme.get("window_opacity", 0.98)))
        self.dialog_opacity = ctk.DoubleVar(value=float(self.theme.get("dialog_opacity", 0.96)))
        self.panel_opacity = ctk.DoubleVar(value=float(self.theme.get("panel_opacity", 0.86)))
        self.button_size = ctk.StringVar(value=self.app.db.get_setting("button_size", self.theme.get("button_size", "Orta")) or "Orta")
        self._button_size_row(form)
        self._slider_row(form, "Pencere Saydamlığı", self.window_opacity)
        self._slider_row(form, "Pencere Detay Saydamlığı", self.dialog_opacity)
        self._slider_row(form, "Panel Doluluğu", self.panel_opacity, from_=0.75, to=1.0)

        ctk.CTkLabel(preview, text="Canlı Önizleme", font=ctk.CTkFont(size=20, weight="bold"), text_color=self.theme["text"]).pack(pady=(28, 12))
        self.preview_card = ctk.CTkFrame(preview, fg_color=self.theme["panel"], corner_radius=14, border_width=1, border_color=self.theme["border"])
        self.preview_card.pack(fill="x", padx=24, pady=10)
        self.preview_label = ctk.CTkLabel(self.preview_card, text="Matadors Club", text_color=self.theme["text"], font=ctk.CTkFont(size=16, weight="bold"))
        self.preview_label.pack(padx=18, pady=(18, 6))
        self.preview_mini = ctk.CTkFrame(self.preview_card, fg_color=self.theme["bg"], corner_radius=10, border_width=1, border_color=self.theme["border"])
        self.preview_mini.pack(fill="x", padx=18, pady=(6, 8))
        self.preview_sidebar = ctk.CTkFrame(self.preview_mini, fg_color=self.theme["sidebar"], width=46, corner_radius=8)
        self.preview_sidebar.pack(side="left", fill="y", padx=8, pady=8)
        mini_content = ctk.CTkFrame(self.preview_mini, fg_color="transparent")
        mini_content.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=8)
        self.preview_top = ctk.CTkFrame(mini_content, fg_color=self.theme["top"], height=18, corner_radius=6)
        self.preview_top.pack(fill="x", pady=(0, 6))
        self.preview_panel = ctk.CTkFrame(mini_content, fg_color=self.theme["panel"], height=44, corner_radius=8, border_width=1, border_color=self.theme["border"])
        self.preview_panel.pack(fill="x")
        self.preview_button = ctk.CTkButton(self.preview_card, text="Örnek Buton", fg_color=self.theme["accent"], hover_color=self.theme["accent_hover"])
        self.preview_button.pack(padx=18, pady=(8, 18))

        actions = ctk.CTkFrame(root, fg_color="transparent")
        actions.pack(fill="x", padx=22, pady=(8, 20))
        ctk.CTkButton(actions, text="Uygula ve Kaydet", height=42, fg_color=t["accent"], hover_color=t["accent_hover"], command=self.apply_theme).pack(side="left", padx=(0, 10))
        ctk.CTkButton(actions, text="Varsayılan Görünüm", height=42, fg_color=t["panel2"], text_color=t["text"], command=self.reset_theme).pack(side="left")
        ctk.CTkButton(actions, text="Kapat", height=42, fg_color=t["danger"], command=self.destroy).pack(side="right")

    def _color_row(self, parent, label, key):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=6)
        ctk.CTkLabel(row, text=label, width=130, anchor="w", text_color=self.app.theme["text"]).pack(side="left", padx=(0, 8))
        var = ctk.StringVar(value=str(self.theme.get(key, DEFAULT_NEON_THEME.get(key, "#000000"))))
        self.vars[key] = var
        swatch = ctk.CTkFrame(row, fg_color=var.get(), width=34, height=30, corner_radius=8)
        swatch.pack(side="left", padx=(0, 8))
        self.swatches[key] = swatch
        ctk.CTkButton(
            row,
            text="Renk Seç",
            height=32,
            fg_color=self.app.theme["panel2"],
            text_color=self.app.theme["text"],
            hover_color=self.app.theme["border"],
            command=lambda k=key: self._choose_color(k),
        ).pack(side="left", fill="x", expand=True)
        var.trace_add("write", lambda *_args, v=var, s=swatch: self._on_color_change(v, s))

    def _slider_row(self, parent, label, var, from_=0.75, to=1.0):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(14, 4))
        ctk.CTkLabel(row, text=label, width=130, anchor="w", text_color=self.app.theme["text"]).pack(side="left")
        ctk.CTkSlider(row, from_=from_, to=to, number_of_steps=25, variable=var, command=lambda _v: self.update_preview()).pack(side="left", fill="x", expand=True, padx=8)
        value_lbl = ctk.CTkLabel(row, text=f"{var.get():.2f}", width=42, text_color=self.app.theme["muted"])
        value_lbl.pack(side="left")
        var.trace_add("write", lambda *_args, v=var, lbl=value_lbl: lbl.configure(text=f"{v.get():.2f}"))

    def _button_size_row(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(14, 4))
        ctk.CTkLabel(row, text="Buton Boyutu", width=130, anchor="w", text_color=self.app.theme["text"]).pack(side="left")
        ctk.CTkOptionMenu(
            row,
            values=list(BUTTON_SIZE_PRESETS.keys()),
            variable=self.button_size,
            command=lambda _v: self.update_preview(),
            fg_color=self.app.theme["panel2"],
            button_color=self.app.theme["accent"],
            button_hover_color=self.app.theme["accent_hover"],
            text_color=self.app.theme["text"],
        ).pack(side="left", fill="x", expand=True, padx=8)

    def _choose_color(self, key):
        current = self.vars[key].get()
        _, picked = colorchooser.askcolor(color=current, title="Renk Seç", parent=self)
        if picked:
            self.vars[key].set(picked)

    def _on_color_change(self, var, swatch):
        color = var.get().strip()
        if self.is_valid_color(color):
            swatch.configure(fg_color=color)
            self.update_preview()

    def update_preview(self):
        for key, var in self.vars.items():
            value = var.get().strip()
            if self.is_valid_color(value):
                self.theme[key] = value
        self.theme["window_opacity"] = f"{self.window_opacity.get():.2f}"
        self.theme["dialog_opacity"] = f"{self.dialog_opacity.get():.2f}"
        self.theme["panel_opacity"] = f"{self.panel_opacity.get():.2f}"
        self.theme["button_size"] = self.button_size.get() or "Orta"
        self._apply_panel_opacity()
        self.preview.configure(fg_color=self.theme["glass"], border_color=self.theme["border"])
        self.preview_card.configure(fg_color=self.theme["panel"], border_color=self.theme["border"])
        self.preview_label.configure(text_color=self.theme["text"])
        self.preview_mini.configure(fg_color=self.theme["bg"], border_color=self.theme["border"])
        self.preview_sidebar.configure(fg_color=self.theme["sidebar"])
        self.preview_top.configure(fg_color=self.theme["top"])
        self.preview_panel.configure(fg_color=self.theme["panel"], border_color=self.theme["border"])
        self.preview_button.configure(
            fg_color=self.theme["accent"],
            hover_color=self.theme["accent_hover"],
            height=BUTTON_SIZE_PRESETS.get(self.theme.get("button_size", "Orta"), BUTTON_SIZE_PRESETS["Orta"]),
        )

    def _apply_panel_opacity(self):
        opacity = max(0.35, min(1.0, float(self.theme.get("panel_opacity", 0.86))))
        bg = self.vars.get("bg").get() if self.vars.get("bg") else self.theme.get("bg", "#f4f7fb")
        for key in ("glass", "panel", "panel2", "input"):
            base = self.vars.get(key).get() if self.vars.get(key) else self.theme.get(key, DEFAULT_NEON_THEME.get(key, "#ffffff"))
            if self.is_valid_color(base) and self.is_valid_color(bg):
                self.theme[key] = self._blend_hex(bg, base, opacity)
                if key in self.swatches:
                    self.swatches[key].configure(fg_color=self.theme[key])

    def _blend_hex(self, bg, fg, amount):
        bg = bg.lstrip("#")
        fg = fg.lstrip("#")
        if len(bg) == 3:
            bg = "".join(ch * 2 for ch in bg)
        if len(fg) == 3:
            fg = "".join(ch * 2 for ch in fg)
        br, bgc, bb = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
        fr, fgc, fb = int(fg[0:2], 16), int(fg[2:4], 16), int(fg[4:6], 16)
        r = int(br * (1 - amount) + fr * amount)
        g = int(bgc * (1 - amount) + fgc * amount)
        b = int(bb * (1 - amount) + fb * amount)
        return f"#{r:02x}{g:02x}{b:02x}"

    def apply_theme(self):
        self.update_preview()
        self.app.db.set_settings({"theme_config": json.dumps(self.theme), "glass_theme_version": "3", "button_size": self.theme.get("button_size", "Orta")})
        self.app.theme = self.theme.copy()
        self.app.apply_theme()
        
        def _close_dialog():
            try:
                messagebox.showinfo("Görünüm", "Görünüm ayarları kaydedildi ve uygulandı.")
            finally:
                self.destroy()
        self.after(10, _close_dialog)

    def reset_theme(self):
        self.theme = DEFAULT_NEON_THEME.copy()
        for key, var in self.vars.items():
            var.set(self.theme[key])
        self.window_opacity.set(float(self.theme["window_opacity"]))
        self.dialog_opacity.set(float(self.theme["dialog_opacity"]))
        self.panel_opacity.set(float(self.theme.get("panel_opacity", 0.86)))
        self.button_size.set(self.theme.get("button_size", "Orta"))
        self.update_preview()

    def is_valid_color(self, color):
        if not isinstance(color, str) or not color.startswith("#") or len(color) not in (4, 7):
            return False
        try:
            int(color[1:], 16)
            return True
        except ValueError:
            return False
