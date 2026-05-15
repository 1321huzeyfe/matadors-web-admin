# -*- coding: utf-8 -*-
import os
import sys
import json
import traceback
import socket
import threading
from datetime import datetime
from pathlib import Path
import sqlite3
from contextlib import closing

import customtkinter as ctk

from database import KasaDatabase
from backup_manager import BackupManager
from cashier_data_store import CashierDataStore
from profile_manager import PROFILE_KASA, PROFILE_MANAGER, ProfileManager
from shared_data_manager import SharedDataManager
from security import SecurityManager
from path_utils import (
    business_day,
    get_app_root,
    get_auth_db_path,
    get_data_dir,
    get_db_path,
    get_kasa_report_month_dir,
    get_logs_dir,
    get_pdf_reports_dir,
    get_reports_dir,
    ensure_standard_data_dirs,
    sanitize_kasa_name,
)
from safe_io import sqlite_online_backup
from safe_io import atomic_copy_file
from services.pdf_fonts import get_pdf_fonts
from services.customer_activity_reports import (
    write_customer_activity_pdf,
)
from services.supabase_sync import bootstrap_profile_once_silent, process_queue_once_silent
from performance import measure, perf_timer
from ui.styles import BUTTON_SIZE_PRESETS
from pages import (
    LoginFrame,
    MainShell,
    THEME_PRESETS,
    write_report_pdf,
)

APP_VERSION = "1.1"
DATA_SCHEMA_VERSION = "2026-05-08.1"


def _executable_dir() -> str:
    """Application root directory for assets and central data/ layout."""
    return get_app_root()


class MatadorsKasaApp(ctk.CTk):
    def __init__(self):
        try:
            super().__init__()
        except Exception as e:
            print(f"CTk initialization error: {e}")
            # Fallback to basic Tk
            import tkinter as tk
            self.root = tk.Tk()
            self.root.title("Matadors Club - VIP Edition")
            self.root.geometry("2560x1440")
            self.root.mainloop()
            return
        
        try:
            # Initialize paths and directories
            self.base_dir = _executable_dir()
            ensure_standard_data_dirs()
            self.data_dir = get_data_dir()
            self.reports_dir = get_reports_dir()
            self.logs_dir = get_logs_dir()
            self.exports_dir = self.reports_dir
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                self.assets_dir = os.path.join(sys._MEIPASS, "assets")
            else:
                self.assets_dir = os.path.join(self.base_dir, "assets")
            self.db_path = get_db_path()
            self.auth_db_path = get_auth_db_path()
            self.profile_manager = ProfileManager(self.data_dir)
            self.cashier_data_store = CashierDataStore()
            self.shared_data_manager = SharedDataManager(self.profile_manager)
            self.current_profile = self.profile_manager.profile_for_user({"username": "manager", "user_type": "admin"})
            self.web_panel_server = None
            self.web_panel_thread = None
            self.supabase_queue_interval_seconds = 60
            self._supabase_queue_lock = threading.Lock()
            self._supabase_queue_stop = threading.Event()
            self._supabase_queue_thread = None
            self._setup_status_cache = None
            
            # Initialize database with error handling
            try:
                self.db = KasaDatabase(self.db_path, self.auth_db_path)
                self._attach_shared_manager(self.db, "admin")
                self.backup_manager = BackupManager(self.db_path, self.db, self.data_dir)
                self.security_manager = SecurityManager(self.db)
                self._ensure_update_safety()
            except Exception as e:
                print(f"Database initialization error: {e}")
                print("Critical: Cannot initialize database. Exiting.")
                self.destroy()
                return
            
            # Migration disabled - migrate_existing_cashiers method not available
            # Database migration handled automatically
            
            self.current_user = None
            self.theme_name = "custom"
            self.theme = THEME_PRESETS["custom"]

            # Window configuration
            self.title("Matadors Club - VIP Edition")
            self.geometry("2560x1440")
            self.minsize(1100, 720)
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            
            # Background image disabled for clean white theme
            
            # Remove window transparency for better visibility
            # Transparency disabled to fix visibility issues
            
            # Theme configuration
            try:
                self.apply_theme()
            except Exception as e:
                print(f"Theme configuration error: {e}")
            
            # Window icon
            try:
                self._apply_window_icon()
            except Exception as e:
                print(f"Window icon error: {e}")
            
            # Check session
            self.run_background_io(
                "startup_backup",
                lambda: self.backup_manager.backup_if_needed("startup"),
                lambda result: print(f"Startup backup: {result.status} - {result.local_path}") if result else None,
            )

            self._bootstrap_supabase_profile_once_async({"id": 1, "username": "admin", "user_type": "admin"})
            self._process_supabase_queue_once_async()
            self._start_supabase_queue_worker()

            try:
                self.check_session()
            except Exception as e:
                print(f"Session check error: {e}")
            self._schedule_end_of_day_check()
                
        except Exception as e:
            print(f"Critical application initialization error: {e}")
            try:
                self.destroy()
            except:
                pass
            sys.exit(1)

    def _process_supabase_queue_once_async(self) -> None:
        """Try queued Supabase sync once on startup without blocking the app."""
        def worker():
            self._process_supabase_queue_safely()

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:
            print(f"Supabase queue thread error: {exc}")

    def _after_ui(self, callback) -> None:
        def safe_callback():
            try:
                callback()
            except Exception as exc:
                print(f"UI callback error: {exc}\n{traceback.format_exc()}")

        try:
            if self.winfo_exists():
                self.after(0, safe_callback)
        except Exception as exc:
            print(f"UI callback schedule error: {exc}")

    def run_background_io(self, name: str, work, on_done=None, on_error=None) -> None:
        """Run slow file/network work off the Tk thread."""
        def worker():
            result = None
            try:
                with perf_timer("arka_plan_is_suresi", name):
                    result = work()
            except Exception as exc:
                print(f"{name} background error: {exc}\n{traceback.format_exc()}")
                if on_error:
                    self._after_ui(lambda exc=exc: on_error(exc))
                return
            if on_done:
                self._after_ui(lambda result=result: on_done(result))

        try:
            threading.Thread(target=worker, name=f"MatadorsBackground-{name}", daemon=True).start()
        except Exception as exc:
            print(f"{name} thread error: {exc}\n{traceback.format_exc()}")
            if on_error:
                self._after_ui(lambda exc=exc: on_error(exc))

    def _bootstrap_supabase_profile_once_async(self, user: dict) -> None:
        """Best-effort first-open pull for the active profile; never blocks login."""
        if not user:
            return

        def worker():
            try:
                with perf_timer("supabase_sync_suresi", "bootstrap_profile_once"):
                    bootstrap_profile_once_silent(self.db_path, dict(user), include_sales=False)
            except Exception:
                pass

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:
            print(f"Supabase bootstrap thread error: {exc}")

    def _process_supabase_queue_safely(self) -> None:
        """Run one queue pass if another pass is not already active."""
        lock = getattr(self, "_supabase_queue_lock", None)
        if lock is None:
            return
        acquired = lock.acquire(blocking=False)
        if not acquired:
            return
        try:
            with perf_timer("queue_isleme_suresi", "limit=100"):
                process_queue_once_silent(limit=100)
        finally:
            lock.release()

    def _start_supabase_queue_worker(self) -> None:
        """Process Supabase queue periodically without blocking UI or SQLite."""
        if getattr(self, "_supabase_queue_thread", None) and self._supabase_queue_thread.is_alive():
            return

        def worker():
            interval = max(5, int(getattr(self, "supabase_queue_interval_seconds", 60) or 60))
            stop_event = getattr(self, "_supabase_queue_stop", None)
            while stop_event is not None and not stop_event.wait(interval):
                try:
                    self._process_supabase_queue_safely()
                except Exception:
                    pass

        try:
            self._supabase_queue_thread = threading.Thread(target=worker, daemon=True)
            self._supabase_queue_thread.start()
        except Exception as exc:
            print(f"Supabase queue periodic thread error: {exc}")

    def _stop_supabase_queue_worker(self) -> None:
        try:
            if hasattr(self, "_supabase_queue_stop"):
                self._supabase_queue_stop.set()
        except Exception:
            pass

    def get_vip_background_image(self):
        """Downloads klasöründeki en son 'arka plan' isimli resmi döner."""
        try:
            from PIL import Image
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            valid_exts = (".png", ".jpg", ".jpeg", ".webp")
            files = [
                os.path.join(downloads, f) for f in os.listdir(downloads) 
                if f.lower().startswith("arka plan") and f.lower().endswith(valid_exts)
            ]
            if not files:
                return None
            # En son değiştirilen dosyayı al
            latest_file = max(files, key=os.path.getmtime)
            return latest_file
        except Exception as e:
            print(f"Arka plan yükleme hatası: {e}")
            return None

    def _apply_background_image(self):
        """Apply background image to the main window."""
        try:
            bg_image_path = self.get_vip_background_image()
            if bg_image_path and os.path.exists(bg_image_path):
                from PIL import Image, ImageTk
                
                # Load and resize image for the application window.
                image = Image.open(bg_image_path)
                image = image.resize((2560, 1440), Image.Resampling.LANCZOS)
                self.bg_photo = ImageTk.PhotoImage(image)
                
                # Create background label
                self.bg_label = ctk.CTkLabel(self, image=self.bg_photo)
                self.bg_label.place(relwidth=1, relheight=1)
                self.bg_label.lower()  # Send to back
                
                print(f"Arka plan uygulandı: {bg_image_path}")
            else:
                print("Arka plan resmi bulunamadı, varsayılan tema kullanılacak")
        except Exception as e:
            print(f"Arka plan uygulama hatası: {e}")
            # Continue without background image

    @measure("startup_gereksiz_islem_kontrolu", lambda self: "update_safety")
    def _ensure_update_safety(self) -> None:
        """Create a one-time backup before version/schema migration metadata changes."""
        previous_app = self.db.get_setting("app_version", "")
        previous_schema = self.db.get_setting("data_schema_version", "")
        if previous_app == APP_VERSION and previous_schema == DATA_SCHEMA_VERSION:
            return
        backup_dir = self._create_update_backup()
        self.db.set_settings(
            {
                "previous_app_version": previous_app,
                "previous_data_schema_version": previous_schema,
                "app_version": APP_VERSION,
                "data_schema_version": DATA_SCHEMA_VERSION,
                "last_update_backup": str(backup_dir),
                "last_update_at": datetime.now().isoformat(timespec="seconds"),
            }
        )

    @measure("backup_suresi", lambda self: "reason=update_safety")
    def _create_update_backup(self) -> Path:
        data_root = Path(self.data_dir)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_dir = data_root / "backups" / f"update_before_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        db_files = [Path(self.db_path), Path(self.auth_db_path)]
        for path in db_files:
            if path.exists():
                sqlite_online_backup(path, backup_dir / path.name)

        config_path = data_root / "config.json"
        if config_path.exists():
            atomic_copy_file(config_path, backup_dir / "config.json")

        manifest = backup_dir / "manifest.json"
        from safe_io import atomic_write_json
        atomic_write_json(
            manifest,
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "app_version_before": self.db.get_setting("app_version", ""),
                "data_schema_version_before": self.db.get_setting("data_schema_version", ""),
                "app_version_after": APP_VERSION,
                "data_schema_version_after": DATA_SCHEMA_VERSION,
                "data_root": str(data_root),
            },
        )
        return backup_dir

    def get_cashier_db(self, username: str = None):
        """Return a database bound to the requested cashier profile."""
        if not username:
            return self.db
        profile = self.profile_manager.ensure_cashier_profile(username)
        current_profile = self.__dict__.get("current_profile")
        if current_profile and current_profile.local_db_path == profile.local_db_path:
            return self.db
        db = KasaDatabase(str(profile.local_db_path), self.auth_db_path)
        self._attach_shared_manager(db, username)
        return db

    def create_cashier_profile(self, username: str, full_name: str, password: str):
        """Create an auth cashier plus its empty isolated data folder/database."""
        username = self.profile_manager.sanitize_profile_name(username)
        if not username:
            raise ValueError("Kasa kullanici adi zorunlu.")
        profile = self.profile_manager.ensure_cashier_profile(username)
        self.db.create_cashier(username, full_name, password)
        user = next((u for u in self.db.list_cashiers() if u.get("username") == username), None)
        if not user:
            raise ValueError("Kasa olusturuldu ancak profil bilgisi okunamadi.")
        cashier_db = self.get_cashier_db(username)
        with closing(sqlite3.connect(cashier_db.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO users(id, username, user_type, full_name, email, archived, is_active)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    user["username"],
                    user["user_type"],
                    user.get("full_name", ""),
                    user.get("email", ""),
                    int(user.get("archived", 0) or 0),
                    int(user.get("is_active", 1) if user.get("is_active") is not None else 1),
                ),
            )
        self.cashier_data_store.ensure_profile_files(profile)
        self.cashier_data_store.export_profile(profile)
        self.db.set_settings({"setup_complete": "1", "setup_cashier_profiles_ready": "1"})
        return user

    def _sync_user_to_cashier_db(self, username: str, user: dict | None = None):
        username = self.profile_manager.sanitize_profile_name(username)
        user = user or next((u for u in self.db.list_users(include_archived=True) if u.get("username") == username), None)
        if not user:
            return
        profile = self.profile_manager.ensure_cashier_profile(username)
        db = KasaDatabase(str(profile.local_db_path), self.auth_db_path)
        self._attach_shared_manager(db, username)
        with closing(sqlite3.connect(db.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO users(id, username, user_type, full_name, email, archived, is_active)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    user["username"],
                    user["user_type"],
                    user.get("full_name", ""),
                    user.get("email", ""),
                    int(user.get("archived", 0) or 0),
                    int(user.get("is_active", 1) if user.get("is_active") is not None else 1),
                ),
            )

    def update_user_password(self, username: str, new_password: str):
        """Update login password in the shared auth DB and refresh local mirrors."""
        username = self.profile_manager.sanitize_profile_name(username)
        self.db.update_user_password(username, new_password)
        user = next((u for u in self.db.list_users(include_archived=True) if u.get("username") == username), None)
        if user and user.get("user_type") == "cashier":
            self._sync_user_to_cashier_db(username, user)
        return user

    def update_cashier_profile(self, cashier_id: int, username: str, full_name: str, password: str = ""):
        """Update cashier auth profile, isolated folder name, local DB mirror and UI cache."""
        new_username = self.profile_manager.sanitize_profile_name(username)
        full_name = (full_name or "").strip()
        if not new_username or not full_name:
            raise ValueError("Kullanici adi ve kasa adi zorunlu.")
        old_user = self.db.get_user_by_id(cashier_id, include_archived=True)
        if not old_user or old_user.get("user_type") != "cashier":
            raise ValueError("Kasa kullanicisi bulunamadi.")
        old_username = self.profile_manager.sanitize_profile_name(old_user.get("username", ""))
        if old_username != new_username:
            self.profile_manager.rename_cashier_profile(old_username, new_username)
        self.db.update_cashier_profile(cashier_id, new_username, full_name)
        if password.strip():
            self.db.update_cashier_password_by_id(cashier_id, password.strip())
        user = self.db.get_user_by_id(cashier_id, include_archived=True)
        self._sync_user_to_cashier_db(new_username, user)
        self.export_cashier_files(new_username)
        current_user = self.__dict__.get("current_user")
        if current_user and current_user.get("id") == cashier_id:
            self.current_user = user
            self.current_profile = self.profile_manager.profile_for_user(user)
        return user

    def passivate_cashier_profile(self, cashier_id: int) -> dict:
        """Soft-disable a cashier without deleting business data."""
        user = self.db.get_user_by_id(cashier_id, include_archived=True)
        if not user or user.get("user_type") != "cashier":
            raise ValueError("Kasa kullanicisi bulunamadi.")
        username = self.profile_manager.sanitize_profile_name(user.get("username", ""))
        updated = self.db.set_cashier_active(cashier_id, False)
        self._sync_cashier_active_state(username, cashier_id, False)
        return updated

    def activate_cashier_profile(self, cashier_id: int) -> dict:
        """Soft-enable a cashier without recreating or deleting data."""
        user = self.db.get_user_by_id(cashier_id, include_archived=True)
        if not user or user.get("user_type") != "cashier":
            raise ValueError("Kasa kullanicisi bulunamadi.")
        username = self.profile_manager.sanitize_profile_name(user.get("username", ""))
        updated = self.db.set_cashier_active(cashier_id, True)
        self._sync_cashier_active_state(username, cashier_id, True)
        return updated

    def _sync_cashier_active_state(self, username: str, cashier_id: int, active: bool) -> None:
        if not username:
            return
        archived = 0 if active else 1
        is_active = 1 if active else 0
        profile = self.profile_manager.ensure_cashier_profile(username)
        if profile.local_db_path.exists():
            with closing(sqlite3.connect(profile.local_db_path)) as conn, conn:
                cur = conn.execute(
                    """
                    UPDATE users SET archived = ?, is_active = ?
                    WHERE id = ? AND user_type = 'cashier'
                    """,
                    (archived, is_active, cashier_id),
                )
                if cur.rowcount == 0:
                    user = self.db.get_user_by_id(cashier_id, include_archived=True)
                    if user:
                        conn.execute(
                            """
                            INSERT INTO users(id, username, user_type, full_name, email, archived, is_active)
                            VALUES(?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                user["id"],
                                user["username"],
                                user["user_type"],
                                user.get("full_name", ""),
                                user.get("email", ""),
                                archived,
                                is_active,
                            ),
                        )
        self.export_cashier_files(username)
        self._setup_status_cache = None

    def _cashier_delete_scope(self, cashier: dict) -> dict:
        username = self.profile_manager.sanitize_profile_name(cashier.get("username", ""))
        cashier_id = int(cashier.get("id") or 0)
        if not username or username in {"manager", "admin", "shared", "genel-kasa", "genel_kasa"}:
            raise ValueError("Bu kasa silinemez.")
        if cashier.get("user_type") != "cashier" or not cashier_id:
            raise ValueError("Sadece gerçek kasa kullanıcıları silinebilir.")
        profile = self.profile_manager.ensure_cashier_profile(username)
        return {
            "cashier_id": cashier_id,
            "username": username,
            "branch_id": username,
            "db_path": profile.local_db_path,
        }

    def _supabase_branch_rows(self, table: str, scope: dict, users: bool = False) -> list[dict]:
        from services.supabase_client import SUPABASE_KEY, SUPABASE_URL
        import requests

        branch = scope["branch_id"]
        cashier_id = str(scope["cashier_id"])
        if users:
            username = scope["username"]
            or_filter = (
                f"(branch_id.eq.{branch},profile_id.eq.{branch},kasa_id.eq.{branch},"
                f"cashier_id.eq.{cashier_id},id.eq.{cashier_id},username.eq.{username})"
            )
        else:
            or_filter = f"(branch_id.eq.{branch},profile_id.eq.{branch},kasa_id.eq.{branch},cashier_id.eq.{cashier_id})"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Accept": "application/json",
        }
        response = requests.get(
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}",
            headers=headers,
            params={"select": "id", "or": or_filter, "limit": "10000"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase {table} okunamadı: {response.status_code} {response.text[:500]}")
        return response.json() if response.text else []

    def _supabase_branch_delete(self, table: str, scope: dict, users: bool = False) -> int:
        raise RuntimeError("Kalici kasa silme devre disi. Kasa pasiflestirme/aktif etme kullanilmali.")

    def cashier_delete_dry_run(self, cashier: dict) -> dict:
        """Count records that would be removed by the hard-delete flow."""
        scope = self._cashier_delete_scope(cashier)
        local = {"customers": 0, "products": 0, "sales": 0}
        db_path = scope["db_path"]
        if db_path.exists():
            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in local:
                    if table in tables:
                        local[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        supabase = {
            "customers": len(self._supabase_branch_rows("customers", scope)),
            "products": len(self._supabase_branch_rows("products", scope)),
            "sales": len(self._supabase_branch_rows("sales", scope)),
            "users": len(self._supabase_branch_rows("users", scope, users=True)),
        }
        return {"scope": scope, "local": local, "supabase": supabase}

    def delete_cashier_branch_data(self, cashier: dict) -> dict:
        """Disabled: cashier data must only be soft-disabled."""
        raise RuntimeError("Kalici kasa silme devre disi. Kasa pasiflestirme/aktif etme kullanilmali.")

    def _apply_window_icon(self):
        ico = os.path.join(self.assets_dir, "app_icon.ico")
        self.window_icon_path = ico if os.path.isfile(ico) else None
        if self.window_icon_path:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    @measure("tema_yukleme_suresi")
    def apply_theme(self, name: str | None = None):
        import json
        # Always use the custom Matadors theme.
        self.theme_name = "custom"
        
        # Try to load saved custom theme from database
        try:
            if hasattr(self, 'db') and self.db:
                saved_theme = self.db.get_setting("theme_config", "")
                if saved_theme and self.db.get_setting("glass_theme_version", "") == "3":
                    loaded_theme = json.loads(saved_theme)
                    self.theme = THEME_PRESETS["custom"].copy()
                    self.theme.update(loaded_theme)
                    print(f"Loaded theme from database: {len(self.theme)} colors")
                else:
                    self.theme = THEME_PRESETS["custom"].copy()
                    self.db.set_settings({"theme_config": json.dumps(self.theme), "glass_theme_version": "3"})
                    print("Using default custom theme")
            else:
                self.theme = THEME_PRESETS["custom"].copy()
                print("No database, using default theme")
        except Exception as e:
            self.theme = THEME_PRESETS["custom"].copy()
            print(f"Theme load error: {e}")
        
        # Match CustomTkinter controls to the saved theme brightness.
        bg = self.theme.get("bg", "#0a0a0a").lstrip("#")
        try:
            r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
            appearance = "light" if ((r * 299 + g * 587 + b * 114) / 1000) > 150 else "dark"
        except Exception:
            appearance = "dark"
        ctk.set_appearance_mode(appearance)
        self.configure(fg_color=self.theme["bg"])
        self.theme["button_size"] = self.db.get_setting("button_size", self.theme.get("button_size", "Orta")) if hasattr(self, "db") else self.theme.get("button_size", "Orta")
        try:
            self.attributes("-alpha", float(self.theme.get("window_opacity", 0.98)))
        except Exception:
            pass
        
        # Keep desktop text crisp without tying the layout to a specific monitor size.
        try:
            import tkinter as tk
            self.tk.call('tk', 'scaling', 1.15)
        except Exception:
            pass
            
        # Apply theme to all existing widgets
        self._apply_theme_to_all_widgets()
        
        print(f"Theme applied: {self.theme_name}")
        
    @measure("tema_widget_uygulama_suresi")
    def _apply_theme_to_all_widgets(self):
        """Apply theme to all existing widgets recursively."""
        try:
            def update_widget(widget, theme):
                try:
                    if hasattr(widget, 'configure'):
                        # Update frame colors - check both dark and light themes
                        if hasattr(widget, 'fg_color'):
                            current_color = widget.cget('fg_color')
                            # Dark backgrounds -> bg
                            if current_color in ["#1a1a1a", "#2d3748", "#475569", "#64748b", "#0a0a0a", "#000000"]:
                                widget.configure(fg_color=theme.get("bg", "#0a0a0a"))
                            # Light backgrounds -> bg
                            elif current_color in ["#f4f7fb", "#ffffff", "#f8fafc", "#eef5fb", "#e8eef6"]:
                                widget.configure(fg_color=theme.get("bg", "#f4f7fb"))
                            # Panel colors
                            elif current_color in ["#333333", "#555555", "#1e293b", "#0f172a"]:
                                widget.configure(fg_color=theme.get("panel", "#1a1a1a"))
                            # Panel surface colors
                            elif current_color in ["#2d3748", "#374151"]:
                                widget.configure(fg_color=theme.get("glass", theme.get("panel", "#1a1a1a")))
                            # Accent colors
                            elif current_color in ["#ff0033", "#ff0066", "#cc0029", "#2563eb", "#1d4ed8"]:
                                widget.configure(fg_color=theme.get("accent", "#ff0033"))
                        
                        # Update text colors
                        if hasattr(widget, 'text_color'):
                            widget.configure(text_color=theme.get("text", "#ffffff"))
                        
                        # Update button colors specifically
                        if 'CTkButton' in str(type(widget)):
                            widget.configure(fg_color=theme.get("accent", "#ff0033"))
                            size_name = theme.get("button_size", "Orta")
                            height = BUTTON_SIZE_PRESETS.get(size_name, BUTTON_SIZE_PRESETS["Orta"])
                            try:
                                widget.configure(height=height)
                            except Exception:
                                pass
                        
                        # Update entry/input colors
                        if 'CTkEntry' in str(type(widget)) and hasattr(widget, 'fg_color'):
                            widget.configure(fg_color=theme.get("input", theme.get("panel", "#333333")),
                                           border_color=theme.get("border", "#555555"))
                    
                    # Recursively update children
                    for child in widget.winfo_children():
                        update_widget(child, theme)
                except Exception as e:
                    pass
            
            # Update all widgets in main window
            update_widget(self, self.theme)
            print("Theme applied to all widgets")
            
        except Exception as e:
            print(f"Theme application error: {e}")
    
    def apply_custom_theme(self, custom_theme):
        """Apply custom theme immediately."""
        self.theme = custom_theme.copy()
        self._apply_theme_to_all_widgets()
        print(f"Custom theme applied: {len(custom_theme)} colors")

    def set_ui_theme(self, name: str):
        self.db.set_settings({"ui_theme": name})
        self.apply_theme(name)
        self.title(self.db.get_setting("app_title", "Matadors Club"))
        if self.current_user:
            self.clear_window()
            MainShell(self, self, self.current_user)

    def clear_window(self):
        for widget in self.winfo_children():
            widget.destroy()

    def get_local_ip(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def web_panel_urls(self) -> list[str]:
        return []

    def is_web_panel_running(self) -> bool:
        thread = getattr(self, "web_panel_thread", None)
        return bool(getattr(self, "web_panel_server", None) and thread and thread.is_alive())

    def start_web_panel(self, password: str, user: dict | None = None) -> dict:
        return {"started": False, "running": False, "urls": [], "message": "Yerel port web paneli pasif. İnternet paneli web_admin_panel klasöründen yayınlanır."}

    def stop_web_panel(self) -> bool:
        server = getattr(self, "web_panel_server", None)
        if not server:
            return False
        try:
            server.shutdown()
            server.server_close()
        finally:
            self.web_panel_server = None
            self.web_panel_thread = None
        return True

    @measure("dashboard_render_suresi", lambda self, logout=True: "show_login")
    def show_login(self, logout: bool = True):
        """Show login screen. If logout=True, clear session (user pressed logout)."""
        try:
            self.stop_web_panel()
        except Exception:
            pass
        if logout:
            # User explicitly logged out - require login next time
            self.db.set_settings({
                "last_session_user": "",
                "last_session_date": "",
                "session_active": "0"
            })
        self.current_user = None
        self.clear_window()
        self.apply_theme()
        LoginFrame(self, self)
    
    @measure("startup_gereksiz_islem_kontrolu", lambda self: "check_session")
    def check_session(self):
        """Check if we can auto-login from previous session (same day, not logged out)."""
        today = datetime.now().strftime("%Y-%m-%d")
        last_date = self.db.get_setting("last_session_date", "")
        last_user_id = self.db.get_setting("last_session_user", "")
        session_active = self.db.get_setting("session_active", "0") == "1"
        
        # If same day and session was active (not logged out), auto-login
        if last_date == today and session_active and last_user_id:
            try:
                user_id = int(last_user_id)
                # Get user from database
                user = self.db.get_user_by_id(user_id)
                if user:
                    self.load_user_panel(user)
                    return
            except (ValueError, TypeError):
                pass
        
        # Otherwise show login
        self.show_login(logout=False)

    @measure("dashboard_render_suresi", lambda self, user: f"load_user_panel user={user.get('username') if isinstance(user, dict) else ''}")
    def load_user_panel(self, user: dict):
        if user.get("user_type") != "admin":
            self.stop_web_panel()
            if not self.is_setup_complete():
                from tkinter import messagebox
                messagebox.showwarning("Kurulum", "Kurulum tamamlanmadan kasa ekranına geçilemez.")
                self.show_login(logout=False)
                return
            ok, message = self.validate_cashier_ready(user.get("username", ""))
            if not ok:
                from tkinter import messagebox
                messagebox.showwarning("Kasa Verisi", message)
                self.show_login(logout=False)
                return
        self.current_user = user
        self._activate_profile_database(user)
        # Save session info for auto-login
        today = datetime.now().strftime("%Y-%m-%d")
        self.db.set_settings({
            "last_session_user": str(user["id"]),
            "last_session_date": today,
            "session_active": "1"
        })
        self._run_auto_end_of_day_if_due_async()
        self.clear_window()
        self.apply_theme()
        self.title(self.db.get_setting("app_title", "Matadors Club"))
        MainShell(self, self, user)

    def _activate_profile_database(self, user: dict):
        """Switch SQLite target according to the selected profile."""
        self.current_profile = self.profile_manager.profile_for_user(user)
        if self.current_profile.profile_type == PROFILE_KASA:
            self.db_path = str(self.current_profile.local_db_path)
            self.reports_dir = str(self.current_profile.reports_dir)
        else:
            self.db_path = get_db_path()
            self.reports_dir = get_reports_dir()
        self.db = KasaDatabase(self.db_path, self.auth_db_path)
        self._attach_shared_manager(self.db, user.get("username", "admin"))
        self.backup_manager = BackupManager(self.db_path, self.db, self.data_dir)
        self.security_manager = SecurityManager(self.db)
        if self.current_profile.profile_type == PROFILE_KASA:
            profile = self.current_profile
            self.run_background_io("cashier_profile_export", lambda: self.cashier_data_store.export_profile(profile))
        self._bootstrap_supabase_profile_once_async(user)

    def _attach_shared_manager(self, db, actor: str):
        db.shared_data_manager = self.shared_data_manager
        db.active_actor = actor
        current_user = self.__dict__.get("current_user") or {}
        db.active_role = "admin" if actor == "admin" or current_user.get("user_type") == "admin" else "cashier"

    def on_close(self):
        """Take a best-effort final backup before closing the desktop app."""
        try:
            self._stop_supabase_queue_worker()
            if hasattr(self, "backup_manager"):
                result = self.backup_manager.create_backup(reason="shutdown")
                print(f"Shutdown backup: {result.status} - {result.local_path or result.error}")
            self.stop_web_panel()
        except Exception as e:
            print(f"Shutdown backup error: {e}")
        finally:
            try:
                self.stop_web_panel()
            except Exception:
                pass
            self.destroy()

    @measure("backup_suresi", lambda self, reason="manual": f"reason={reason}")
    def create_manual_backup(self, reason: str = "manual"):
        if not hasattr(self, "backup_manager"):
            raise RuntimeError("Yedekleme sistemi baslatilamadi.")
        result = self.backup_manager.create_backup(reason=reason)
        return result

    def set_drive_sync_root(self, folder: str):
        return ""

    @measure("gereksiz_dosya_taramasi", lambda self, root=None: f"scan_drive_business_data root={root or ''}")
    def scan_drive_business_data(self, root: str | Path | None = None) -> dict:
        kasa_dirs = []
        sales_files = []
        active_profiles = [self.profile_manager.sanitize_profile_name(row.get("username", "")) for row in self.db.list_cashiers()]
        local_cache = {}
        for kasa in sorted(set(active_profiles)):
            profile = self.profile_manager.ensure_cashier_profile(kasa)
            local_cache[kasa] = profile.local_db_path.exists() and profile.local_db_path.stat().st_size > 0
        missing_cache = [kasa for kasa, ready in local_cache.items() if not ready]
        return {
            "drive_root": "",
            "has_data": False,
            "kasalar": sorted(kasa_dirs),
            "kasa_count": len(kasa_dirs),
            "sales_files": sales_files,
            "active_profiles": sorted(active_profiles),
            "local_cache": local_cache,
            "missing_cache": sorted(missing_cache),
            "missing_drive": [],
            "unprofiled_drive": [],
            "mismatches": sorted(missing_cache),
        }

    def import_drive_cache_readonly(self) -> dict:
        """Drive cache import is disabled; local SQLite remains the source of truth."""
        return {"imported": [], **self.scan_drive_business_data()}

    def _latest_existing_db(self, paths: list[Path]) -> Path | None:
        existing = [path for path in paths if path.exists() and path.is_file() and path.stat().st_size > 0]
        if not existing:
            return None
        return max(existing, key=lambda path: path.stat().st_mtime)

    @measure("gereksiz_dosya_taramasi", lambda self, username: f"find_cashier_sales_sources user={username}")
    def find_cashier_sales_sources(self, username: str) -> dict:
        """List candidate sales DB sources without copying, renaming or modifying them."""
        kasa = self.profile_manager.sanitize_profile_name(username)
        profile = self.profile_manager.ensure_cashier_profile(kasa)
        data_root = Path(self.data_dir)
        local_candidates = [
            profile.local_db_path,
            data_root / "local" / f"{kasa}.db",
            data_root / "local" / f"{kasa}.sqlite",
        ]
        backup_candidates = []
        for backup_root in (
            profile.kasa_backups_dir,
        ):
            if backup_root.exists():
                backup_candidates.extend(
                    path for path in backup_root.rglob("*")
                    if path.is_file() and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
                )
        return {
            "kasa": kasa,
            "local": self._latest_existing_db(local_candidates),
            "latest_backup": self._latest_existing_db(backup_candidates),
            "drive_sync": None,
            "expected_drive": None,
            "expected_local": profile.local_db_path,
        }

    def resolve_cashier_sales_db_for_read(self, username: str) -> Path | None:
        sources = self.find_cashier_sales_sources(username)
        return sources["local"] or sources["latest_backup"] or sources["drive_sync"]

    def validate_cashier_ready(self, username: str) -> tuple[bool, str]:
        kasa = self.profile_manager.sanitize_profile_name(username)
        if not kasa:
            return False, "Kasa profili geçersiz."
        profile = self.profile_manager.ensure_cashier_profile(kasa)
        if profile.local_db_path.exists() and profile.local_db_path.stat().st_size > 0:
            return True, "Kasa verisi local DB ile hazır."
        return False, f"Kasa satış verisi bulunamadı. Kontrol edilen öncelikli yol:\n{profile.local_db_path}"

    def is_setup_complete(self) -> bool:
        if self.db.get_setting("setup_complete", "") == "1":
            return True
        has_cashier = len(self.db.list_cashiers()) > 0
        complete = has_cashier
        if complete:
            self.db.set_settings({"setup_complete": "1"})
        return complete

    def setup_status(self) -> dict:
        now_ts = datetime.now().timestamp()
        cached = getattr(self, "_setup_status_cache", None)
        if cached and now_ts - cached[0] < 3:
            return dict(cached[1])
        cashiers = self.db.list_cashiers()
        status = {
            "drive_root": "",
            "cloud_selected": False,
            "data_found": False,
            "data_read": True,
            "cashier_ready": bool(cashiers),
            "cashier_count": len(cashiers),
            "active_profiles": [self.profile_manager.sanitize_profile_name(row.get("username", "")) for row in cashiers],
            "drive_kasalar": [],
            "local_cache": {},
            "missing_cache": [],
            "missing_drive": [],
            "unprofiled_drive": [],
            "mismatches": [],
            "app_version": self.db.get_setting("app_version", APP_VERSION),
            "data_schema_version": self.db.get_setting("data_schema_version", DATA_SCHEMA_VERSION),
            "data_dir": str(self.data_dir),
            "last_update_backup": self.db.get_setting("last_update_backup", ""),
            "web_panel_note": "Web Panel şu anda aktif kullanımda değil.",
            "complete": self.is_setup_complete(),
        }
        self._setup_status_cache = (now_ts, dict(status))
        return status

    def get_drive_sync_root(self):
        return self.profile_manager.read_drive_root_setting()

    def get_manager_sync_statuses(self):
        return []

    def list_kasa_sources(self):
        """Return only cashiers created by the administrator."""
        rows = []
        seen = set()
        try:
            for row in self.db.list_cashiers():
                item = dict(row)
                item["username"] = self.profile_manager.sanitize_profile_name(item.get("username", ""))
                rows.append(item)
                seen.add(item["username"])
        except Exception:
            pass
        return rows

    def sync_current_profile_now(self):
        return None

    def export_cashier_files(self, username: str | None = None):
        profile = self.profile_manager.ensure_cashier_profile(username or self.current_profile.username)
        return self.cashier_data_store.export_profile(profile)

    def read_cashier_customers_file(self, username: str, search_text: str = ""):
        profile = self.profile_manager.ensure_cashier_profile(username)
        self.cashier_data_store.export_profile(profile)
        return self.cashier_data_store.read_customers(profile, search_text)

    def find_similar_customer_by_phone(self, phone: str):
        try:
            return self.shared_data_manager.find_similar_customer_by_phone(phone)
        except Exception:
            return []

    def effective_stock_map(self):
        try:
            return self.shared_data_manager.effective_stock_map()
        except Exception:
            return {}

    @measure("musteri_kayit_suresi", lambda self, user, data: f"user={user.get('username') if isinstance(user, dict) else ''}")
    def create_customer_for_user(self, user: dict, data: dict):
        cashier_id = user["id"] if user.get("user_type") != "admin" else 0
        target_db = self.db
        if user.get("user_type") != "admin" and user.get("username"):
            target_db = self.get_cashier_db(user.get("username"))
        cid = target_db.add_customer(
            data["name"],
            data.get("phone", ""),
            data.get("avatar", ""),
            float(data.get("balance", 0)),
            float(data.get("credit_limit", -150)),
            data.get("note", ""),
            cashier_id=cashier_id,
        )
        if user.get("user_type") == "admin":
            customer = target_db.get_customer(cid)
            self.shared_data_manager.add_customer_master(customer, actor=user.get("username", "admin"), cashier_id=0)
            try:
                with closing(sqlite3.connect(target_db.db_path)) as conn, conn:
                    conn.execute("UPDATE customers SET pending_sync = 0 WHERE id = ?", (cid,))
            except Exception:
                pass
        return cid

    def archive_report_to_drive(self, path: str, report_type: str = "reports"):
        return ""

    def _reports_dir_for_cashier(self, cashier_id: int | None) -> str:
        if cashier_id is not None:
            cashier = self.db.get_user_by_id(cashier_id)
            if cashier and cashier.get("username"):
                profile = self.profile_manager.ensure_cashier_profile(cashier["username"])
                return str(profile.kasa_reports_dir)
        return str(self.reports_dir)

    def _report_month_dir_for_cashier(self, cashier_id: int | None, report_date: str) -> str:
        if cashier_id is not None:
            cashier = self.db.get_user_by_id(cashier_id)
            if cashier and cashier.get("username"):
                return str(get_kasa_report_month_dir(cashier["username"], report_date, self.data_dir))
        return str(get_kasa_report_month_dir("manager", report_date, self.data_dir))

    def _schedule_end_of_day_check(self):
        try:
            self.after(60_000, self._auto_end_of_day_check)
        except Exception:
            pass

    def _auto_end_of_day_check(self):
        self._run_auto_end_of_day_if_due_async()
        self._schedule_end_of_day_check()

    def _run_auto_end_of_day_if_due_async(self):
        user = dict(self.current_user or {})
        if not user or user.get("user_type") != "cashier":
            return
        self.run_background_io("end_of_day_check", lambda: self.run_auto_end_of_day_if_due())

    def run_auto_end_of_day_if_due(self, now: datetime | None = None):
        now = now or datetime.now()
        if now.strftime("%H:%M") < "23:30":
            return []
        if not self.current_user or self.current_user.get("user_type") != "cashier":
            return []
        report_date = business_day(now)
        setting_key = f"end_of_day_done_{report_date}"
        if self.db.get_setting(setting_key, "") == "1":
            return []
        cashier_id = self.current_user["id"]
        outputs = [
            self.create_report_pdf(report_date, cashier_id),
            self.create_defter_balance_pdf(cashier_id, report_date=report_date),
        ]
        self.db.set_settings({setting_key: "1", "last_end_of_day_pdf": report_date})
        return outputs

    def manager_drive_daily_data(self, target_date: str):
        """Read all cashier local sales.db files without modifying them."""
        cashiers = self.db.list_cashiers()
        summaries = []
        transactions = []
        totals = {"ciro": 0.0, "yukleme": 0.0, "pos_total": 0.0, "pos_sale_count": 0, "islem_sayisi": 0}
        for cashier in cashiers:
            profile = self.profile_manager.ensure_cashier_profile(cashier["username"])
            source_db = self.resolve_cashier_sales_db_for_read(cashier["username"]) or profile.local_db_path
            data = self._read_drive_daily_for_cashier(source_db, target_date, cashier)
            totals["ciro"] += data["ciro"]
            totals["yukleme"] += data["yukleme"]
            totals["pos_total"] += data["pos_total"]
            totals["pos_sale_count"] += data["pos_sale_count"]
            totals["islem_sayisi"] += data["islem_sayisi"]
            summaries.append(
                {
                    "cashier_id": cashier["id"],
                    "username": cashier["username"],
                    "full_name": cashier["full_name"],
                    "ciro": data["ciro"],
                    "yukleme": data["yukleme"],
                    "pos_total": data["pos_total"],
                }
            )
            transactions.extend(data["transactions"])
        transactions.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return {"date": target_date, "summaries": summaries, "transactions": transactions, **totals}

    def _read_drive_daily_for_cashier(self, db_path: Path, target_date: str, cashier: dict):
        empty = {"transactions": [], "ciro": 0.0, "yukleme": 0.0, "pos_total": 0.0, "pos_sale_count": 0, "islem_sayisi": 0}
        if not db_path.exists():
            return empty
        uri = f"file:{db_path.as_posix()}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "transactions" in tables:
                    tx_rows = conn.execute(
                        """
                        SELECT t.id, t.created_at, t.action_type, t.amount, t.note,
                               COALESCE(c.name, '-') AS customer_name
                        FROM transactions t
                        LEFT JOIN customers c ON c.id = t.customer_id
                        WHERE date(t.created_at) = ?
                        ORDER BY t.id DESC
                        """,
                        (target_date,),
                    ).fetchall()
                    empty["transactions"] = [
                        {**dict(row), "cashier_name": cashier.get("full_name") or cashier.get("username")}
                        for row in tx_rows
                    ]
                    for row in tx_rows:
                        amount = float(row["amount"] or 0)
                        if row["action_type"] == "spend":
                            empty["ciro"] += abs(amount)
                        elif row["action_type"] == "load":
                            empty["yukleme"] += amount
                    empty["islem_sayisi"] = len(tx_rows)
                if "sales" in tables:
                    sale_rows = conn.execute(
                        """
                        SELECT s.id, s.created_at, s.total, s.payment_method, s.note,
                               COALESCE(c.name, 'Misafir') AS customer_name
                        FROM sales s
                        LEFT JOIN customers c ON c.id = s.customer_id
                        WHERE date(s.created_at) = ?
                        ORDER BY s.id DESC
                        """,
                        (target_date,),
                    ).fetchall()
                    empty["transactions"].extend(
                        {
                            "id": row["id"],
                            "created_at": row["created_at"],
                            "action_type": f"SATIŞ/{row['payment_method']}",
                            "amount": float(row["total"] or 0),
                            "note": row["note"],
                            "customer_name": row["customer_name"],
                            "cashier_name": cashier.get("full_name") or cashier.get("username"),
                        }
                        for row in sale_rows
                    )
                    sale = conn.execute(
                        "SELECT COALESCE(SUM(total), 0) AS total, COUNT(*) AS count_value FROM sales WHERE date(created_at) = ?",
                        (target_date,),
                    ).fetchone()
                    empty["pos_total"] = float(sale["total"] or 0)
                    empty["pos_sale_count"] = int(sale["count_value"] or 0)
        except Exception as exc:
            print(f"Drive salt-okunur rapor hatası ({db_path}): {exc}")
        return empty

    @measure("pdf_olusturma_suresi", lambda self, report_date, cashier_id: f"customer_activity date={report_date} cashier_id={cashier_id}")
    def create_customer_activity_archives(self, report_date: str, cashier_id: int | None):
        """Save daily, weekly and monthly customer activity records as PDF only."""
        from datetime import date, timedelta

        selected = date.fromisoformat(report_date)
        week_start = selected - timedelta(days=selected.weekday())
        week_end = week_start + timedelta(days=6)
        month_start = selected.replace(day=1)
        if selected.month == 12:
            next_month = selected.replace(year=selected.year + 1, month=1, day=1)
        else:
            next_month = selected.replace(month=selected.month + 1, day=1)
        month_end = next_month - timedelta(days=1)

        periods = [
            ("gunluk", "Günlük", selected, selected, selected.strftime("%Y-%m")),
            ("haftalik", "Haftalık", week_start, week_end, f"{selected.year}-W{selected.isocalendar().week:02d}"),
            ("aylik", "Aylık", month_start, month_end, selected.strftime("%Y-%m")),
        ]
        scope = "tum_kasalar" if cashier_id is None else f"kasiyer_{cashier_id}"
        outputs = []
        report_base_dir = get_pdf_reports_dir()

        for key, label, start, end, folder_name in periods:
            data = self.db.customer_activity_between(start.isoformat(), end.isoformat(), cashier_id=cashier_id)
            report_dir = report_base_dir
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            base_name = f"musteri_islem_{key}_{start.isoformat()}_{end.isoformat()}_{scope}_{stamp}"
            pdf_path = report_dir / f"{base_name}.pdf"
            title = f"Matadors Müşteri İşlem Kaydı - {label}"
            period_label = f"Dönem: {start.isoformat()} - {end.isoformat()}"
            write_customer_activity_pdf(str(pdf_path), title, period_label, data["rows"], data["summary"], self.base_dir)
            outputs.append(
                {
                    "period": label,
                    "pdf": str(pdf_path),
                    "drive_pdf": "",
                    "summary": data["summary"],
                }
            )
        return outputs

    @measure("pdf_olusturma_suresi", lambda self, report_date, cashier_id: f"daily_report date={report_date} cashier_id={cashier_id}")
    def create_report_pdf(self, report_date: str, cashier_id: int | None):
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.pdfgen import canvas
            from reportlab.lib.colors import HexColor, white, black
            from reportlab.lib.units import cm
        except ImportError as e:
            raise ImportError(f"PDF kütüphanesi yüklenemedi: {e}")

        try:
            report = self.db.daily_report(report_date, cashier_id=cashier_id)
            sales_detail = self.db.daily_sales_detail(report_date, cashier_id=cashier_id)
            expenses = self.db.list_expenses(cashier_id=cashier_id, date_str=report_date) if cashier_id else []
            expenses_total = sum(float(e["amount"]) for e in expenses)
        except Exception as e:
            raise RuntimeError(f"Veri alınırken hata: {e}")

        # Ensure reports directory exists with full path
        report_dir = os.path.abspath(self._report_month_dir_for_cashier(cashier_id, report_date))
        try:
            os.makedirs(report_dir, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Rapor klasörü oluşturulamadı ({report_dir}): {e}")

        scope = "tum_kasalar" if cashier_id is None else f"kasiyer_{cashier_id}"
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"rapor_{report_date}_{scope}_{date_str}.pdf"
        path = os.path.join(report_dir, file_name)

        try:
            pdf = canvas.Canvas(path, pagesize=landscape(A4))
            regular_font, bold_font, italic_font = get_pdf_fonts(self.base_dir)
        except Exception as e:
            raise RuntimeError(f"PDF oluşturulamadı ({path}): {e}")

        width, height = landscape(A4)
        margin = 1.5 * cm

        # Header colors
        header_bg = HexColor("#8B0000")  # Dark red
        text_color = black
        light_bg = HexColor("#F5F5F5")

        y = height - margin

        # Title
        pdf.setFont(bold_font, 18)
        pdf.setFillColor(header_bg)
        pdf.drawString(margin, y, f"Matadors Raporu - {report_date}")
        y -= 1.2 * cm

        # Summary section
        pdf.setFont(bold_font, 12)
        pdf.setFillColor(black)
        pdf.drawString(margin, y, "GÜNLÜK ÖZET")
        y -= 0.6 * cm

        pdf.setFont(regular_font, 10)
        summary_lines = [
            f"POS Satış Toplamı: {report['pos_total']:,.2f} TL ({report['pos_sale_count']} satış)",
            f"Bakiye Harcama: {report['ciro']:,.2f} TL",
            f"Bakiye Yükleme: {report['yukleme']:,.2f} TL",
        ]
        if expenses:
            summary_lines.append(f"Diger Giderler: {expenses_total:,.2f} TL")
        summary_lines.append(f"Net Kasa: {(report['pos_total'] + report['ciro'] - expenses_total):,.2f} TL")

        for line in summary_lines:
            pdf.drawString(margin + 0.5*cm, y, line)
            y -= 0.4 * cm

        y -= 0.5 * cm

        # Payment distribution
        pdf.setFont(bold_font, 11)
        pdf.drawString(margin, y, "ÖDEME DAĞILIMI")
        y -= 0.5 * cm

        pdf.setFont(regular_font, 9)
        for t in sales_detail["totals"]:
            pdf.drawString(margin + 0.5*cm, y, f"{t['payment_method']}: {t['count_value']} adet / {t['total_amount']:,.2f} TL")
            y -= 0.35 * cm

        y -= 0.5 * cm

        # Sales table header
        pdf.setFont(bold_font, 11)
        pdf.setFillColor(header_bg)
        pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.drawString(margin + 0.3*cm, y - 0.15*cm, "SATIŞ DETAYLARI")
        y -= 0.8 * cm

        # Table headers
        col_widths = [2.5*cm, 5*cm, 3*cm, 8*cm, 3*cm]
        headers = ["Saat", "Müşteri", "Ödeme", "Ürünler", "Tutar"]
        x_positions = [margin]
        for w in col_widths[:-1]:
            x_positions.append(x_positions[-1] + w)

        pdf.setFillColor(light_bg)
        pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.5*cm, fill=1, stroke=1)
        pdf.setFillColor(black)
        pdf.setFont(bold_font, 9)

        for i, header in enumerate(headers):
            pdf.drawString(x_positions[i] + 0.2*cm, y - 0.15*cm, header)
        y -= 0.6 * cm

        # Sales rows
        pdf.setFont(regular_font, 8)
        row_height = 0.4 * cm
        alt_row = False

        for s in sales_detail["sales"]:
            if y < margin + 2*cm:
                pdf.showPage()
                y = height - margin
                # Redraw headers
                pdf.setFillColor(light_bg)
                pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.5*cm, fill=1, stroke=1)
                pdf.setFillColor(black)
                pdf.setFont(bold_font, 9)
                for i, header in enumerate(headers):
                    pdf.drawString(x_positions[i] + 0.2*cm, y - 0.15*cm, header)
                y -= 0.6 * cm
                pdf.setFont(regular_font, 8)

            # Alternate row color
            if alt_row:
                pdf.setFillColor(light_bg)
                pdf.rect(margin, y - 0.35*cm, width - 2*margin, row_height, fill=1, stroke=0)
            alt_row = not alt_row

            pdf.setFillColor(black)

            # Get sale items
            items = [it["product_name"] for it in sales_detail["items"] if it["sale_id"] == s["id"]]
            items_str = ", ".join(items[:3])
            if len(items) > 3:
                items_str += "..."

            # Customer name - show "Müşteri" if no customer, otherwise show customer name
            cust_name = s["customer_name"] if s["customer_name"] else "Müşteri"

            # Row data
            saat = s['created_at'][11:16]
            odeme = s['payment_method']
            tutar = f"{s['total']:,.2f} TL"

            # Draw row
            pdf.drawString(x_positions[0] + 0.2*cm, y - 0.15*cm, saat)
            pdf.drawString(x_positions[1] + 0.2*cm, y - 0.15*cm, cust_name[:25])
            pdf.drawString(x_positions[2] + 0.2*cm, y - 0.15*cm, odeme)
            pdf.drawString(x_positions[3] + 0.2*cm, y - 0.15*cm, items_str[:40])
            pdf.drawRightString(x_positions[4] + col_widths[4] - 0.2*cm, y - 0.15*cm, tutar)

            y -= row_height

        # Expenses section
        if expenses:
            y -= 0.5 * cm
            if y < margin + 3*cm:
                pdf.showPage()
                y = height - margin

            pdf.setFont(bold_font, 11)
            pdf.setFillColor(header_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
            pdf.setFillColor(white)
            pdf.drawString(margin + 0.3*cm, y - 0.15*cm, "DİĞER GİDERLER")
            y -= 0.8 * cm

            # Expense headers
            pdf.setFillColor(light_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.5*cm, fill=1, stroke=1)
            pdf.setFillColor(black)
            pdf.setFont(bold_font, 9)
            pdf.drawString(margin + 0.2*cm, y - 0.15*cm, "Saat")
            pdf.drawString(margin + 3*cm, y - 0.15*cm, "Gider Adı")
            pdf.drawString(margin + 10*cm, y - 0.15*cm, "Not")
            pdf.drawRightString(width - margin - 0.2*cm, y - 0.15*cm, "Tutar")
            y -= 0.6 * cm

            # Expense rows
            pdf.setFont(regular_font, 8)
            for exp in expenses:
                if y < margin + 2*cm:
                    pdf.showPage()
                    y = height - margin

                exp_time = exp['created_at'][11:16] if exp['created_at'] else "--:--"
                exp_name = exp['name'][:30]
                exp_note = exp['note'][:25] if exp['note'] else ""
                exp_amount = f"{float(exp['amount']):,.2f} TL"

                pdf.drawString(margin + 0.2*cm, y - 0.15*cm, exp_time)
                pdf.drawString(margin + 3*cm, y - 0.15*cm, exp_name)
                pdf.drawString(margin + 10*cm, y - 0.15*cm, exp_note)
                pdf.drawRightString(width - margin - 0.2*cm, y - 0.15*cm, exp_amount)
                y -= 0.35*cm

            # Expenses total
            pdf.setFont(bold_font, 9)
            pdf.drawString(margin + 10*cm, y - 0.15*cm, "Toplam Gider:")
            pdf.drawRightString(width - margin - 0.2*cm, y - 0.15*cm, f"{expenses_total:,.2f} TL")
            y -= 0.5*cm

        # New customers section
        today_customers = self._get_today_new_customers(report_date, cashier_id)
        if today_customers:
            y -= 0.5 * cm
            if y < margin + 3*cm:
                pdf.showPage()
                y = height - margin

            pdf.setFont(bold_font, 11)
            pdf.setFillColor(header_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
            pdf.setFillColor(white)
            pdf.drawString(margin + 0.3*cm, y - 0.15*cm, f"YENİ EKLENEN MÜŞTERİLER ({len(today_customers)} kişi)")
            y -= 0.8 * cm

            pdf.setFont(regular_font, 9)
            for cust in today_customers[:10]:  # Show first 10
                if y < margin + 2*cm:
                    pdf.showPage()
                    y = height - margin
                cust_time = cust['created_at'][11:16] if cust['created_at'] else ""
                pdf.drawString(margin + 0.2*cm, y - 0.15*cm, f"- {cust['name']} (Saat: {cust_time})")
                y -= 0.35*cm

        # Customer loads section
        today_loads = self._get_today_customer_loads(report_date, cashier_id)
        if today_loads:
            y -= 0.5 * cm
            if y < margin + 3*cm:
                pdf.showPage()
                y = height - margin

            pdf.setFont(bold_font, 11)
            pdf.setFillColor(header_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
            pdf.setFillColor(white)
            pdf.drawString(margin + 0.3*cm, y - 0.15*cm, "BAKİYE YÜKLEMELERİ")
            y -= 0.8 * cm

            # Load headers
            pdf.setFillColor(light_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.5*cm, fill=1, stroke=1)
            pdf.setFillColor(black)
            pdf.setFont(bold_font, 9)
            pdf.drawString(margin + 0.2*cm, y - 0.15*cm, "Saat")
            pdf.drawString(margin + 3*cm, y - 0.15*cm, "Müşteri")
            pdf.drawRightString(width - margin - 0.2*cm, y - 0.15*cm, "Yüklenen Tutar")
            y -= 0.6 * cm

            # Load rows
            pdf.setFont(regular_font, 8)
            total_loads = 0.0
            for load in today_loads:
                if y < margin + 2*cm:
                    pdf.showPage()
                    y = height - margin

                load_time = load['created_at'][11:16] if load['created_at'] else "--:--"
                load_amount = float(load['amount'])
                total_loads += load_amount

                pdf.drawString(margin + 0.2*cm, y - 0.15*cm, load_time)
                pdf.drawString(margin + 3*cm, y - 0.15*cm, load['customer_name'][:30])
                pdf.drawRightString(width - margin - 0.2*cm, y - 0.15*cm, f"{load_amount:,.2f} TL")
                y -= 0.35*cm

            # Loads total
            pdf.setFont(bold_font, 9)
            pdf.drawString(margin + 3*cm, y - 0.15*cm, "Toplam Yükleme:")
            pdf.drawRightString(width - margin - 0.2*cm, y - 0.15*cm, f"{total_loads:,.2f} TL")

        pdf.save()
        self.archive_report_to_drive(path, "gunluk")
        return path

    def _get_today_new_customers(self, date_str: str, cashier_id: int | None):
        """Get customers added today."""
        import sqlite3
        from contextlib import closing
        where = "date(created_at) = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1"
        params = [date_str]
        if cashier_id is not None:
            where += " AND cashier_id = ?"
            params.append(cashier_id)
        with closing(self.db._connect()) as conn:
            rows = conn.execute(
                f"SELECT name, created_at FROM customers WHERE {where} ORDER BY created_at",
                params
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_today_customer_loads(self, date_str: str, cashier_id: int | None):
        """Get balance loads made today."""
        import sqlite3
        from contextlib import closing
        where = (
            "date(t.created_at) = ? AND t.action_type = 'load' "
            "AND COALESCE(t.archived, 0) = 0 AND COALESCE(t.is_active, 1) = 1 "
            "AND COALESCE(c.archived, 0) = 0 AND COALESCE(c.is_active, 1) = 1"
        )
        params = [date_str]
        if cashier_id is not None:
            where += " AND t.cashier_id = ?"
            params.append(cashier_id)
        with closing(self.db._connect()) as conn:
            rows = conn.execute(
                f"""SELECT t.created_at, t.amount, c.name as customer_name
                    FROM transactions t
                    INNER JOIN customers c ON c.id = t.customer_id
                    WHERE {where}
                    ORDER BY t.created_at""",
                params
            ).fetchall()
        return [dict(row) for row in rows]

    def backup_to_drive(self):
        result = self.create_manual_backup(reason="manual")
        if result.ok:
            return result.message
        raise RuntimeError(result.message)

    def test_drive_backup_connection(self):
        raise RuntimeError("Google Drive bağlantısı pasif. Supabase senkron sistemi kullanılacak.")

    @measure("pdf_olusturma_suresi", lambda self, customer_id, cashier_id: f"customer_report customer_id={customer_id} cashier_id={cashier_id}")
    def create_customer_report_pdf(self, customer_id: int, cashier_id: int | None):
        """Generate comprehensive PDF report for a specific customer.
        
        Args:
            customer_id: The customer ID to generate report for
            cashier_id: If None (admin), shows all data. If set, filters by that cashier.
        """
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.pdfgen import canvas
            from reportlab.lib.colors import HexColor, white, black
            from reportlab.lib.units import cm
        except ImportError as e:
            raise ImportError(f"PDF kütüphanesi yüklenemedi: {e}")

        try:
            # Get customer report data
            report = self.db.customer_report(customer_id, cashier_id=cashier_id)
        except Exception as e:
            raise RuntimeError(f"Veri alınırken hata: {e}")

        # Ensure reports directory exists
        report_dir = os.path.abspath(self._report_month_dir_for_cashier(cashier_id, datetime.now().strftime("%Y-%m-%d")))
        try:
            os.makedirs(report_dir, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Rapor klasörü oluşturulamadı ({report_dir}): {e}")

        customer_name = report["customer"]["name"].replace(" ", "_")
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        scope = "tum_kasalar" if cashier_id is None else f"kasa_{cashier_id}"
        file_name = f"musteri_raporu_{customer_name}_{scope}_{date_str}.pdf"
        path = os.path.join(report_dir, file_name)

        try:
            pdf = canvas.Canvas(path, pagesize=landscape(A4))
            regular_font, bold_font, italic_font = get_pdf_fonts(self.base_dir)
        except Exception as e:
            raise RuntimeError(f"PDF oluşturulamadı ({path}): {e}")

        width, height = landscape(A4)
        margin = 1.5 * cm

        # Colors
        header_bg = HexColor("#8B0000")  # Dark red
        text_color = black
        light_bg = HexColor("#F5F5F5")
        accent_bg = HexColor("#2C3E50")

        y = height - margin

        customer = report["customer"]
        summary = report["summary"]

        # Title
        pdf.setFont(bold_font, 20)
        pdf.setFillColor(header_bg)
        pdf.drawString(margin, y, f"Müşteri Raporu - {customer['name']}")
        y -= 1.0 * cm

        # Customer info
        pdf.setFont(regular_font, 10)
        pdf.setFillColor(black)
        pdf.drawString(margin, y, f"Telefon: {customer.get('phone', '-')}")
        pdf.drawString(margin + 8*cm, y, f"Bakiye: {summary['current_balance']:,.2f} TL")
        pdf.drawString(margin + 16*cm, y, f"Kredi Limiti: {float(customer.get('credit_limit', 0)):,.2f} TL")
        y -= 0.8 * cm

        # Summary section
        pdf.setFont(bold_font, 12)
        pdf.setFillColor(accent_bg)
        pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.drawString(margin + 0.3*cm, y - 0.15*cm, "FİNANSAL ÖZET")
        y -= 0.8 * cm

        pdf.setFont(regular_font, 10)
        pdf.setFillColor(black)
        summary_data = [
            f"Toplam Yükleme: {summary['total_yukleme']:,.2f} TL",
            f"Toplam Harcama (Bakiye): {summary['total_harcama']:,.2f} TL",
            f"POS Satışları (Nakit/KK): {summary['total_pos']:,.2f} TL",
            f"Defter Satışları: {summary['total_defter']:,.2f} TL",
            f"İşlem Sayısı: {summary['transaction_count']} yükleme/harcama",
            f"Satış Sayısı: {summary['sale_count']} adet",
        ]
        for line in summary_data:
            pdf.drawString(margin + 0.5*cm, y, line)
            y -= 0.4 * cm

        y -= 0.5 * cm

        # Transactions section
        if report["transactions"]:
            pdf.setFont(bold_font, 12)
            pdf.setFillColor(accent_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
            pdf.setFillColor(white)
            pdf.drawString(margin + 0.3*cm, y - 0.15*cm, "BAKİYE İŞLEMLERİ (Yükleme / Harcama)")
            y -= 0.8 * cm

            # Table headers
            col_widths = [3*cm, 4*cm, 3*cm, 8*cm, 3*cm]
            headers = ["Tarih", "Kasa", "Tip", "Not", "Tutar"]
            x_positions = [margin]
            for w in col_widths[:-1]:
                x_positions.append(x_positions[-1] + w)

            pdf.setFillColor(light_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.5*cm, fill=1, stroke=1)
            pdf.setFillColor(black)
            pdf.setFont(bold_font, 9)
            for i, h in enumerate(headers):
                pdf.drawString(x_positions[i] + 0.2*cm, y - 0.15*cm, h)
            y -= 0.6 * cm

            # Transaction rows
            pdf.setFont(regular_font, 8)
            for tx in report["transactions"][:50]:  # Limit to 50 for space
                if y < margin + 2*cm:
                    pdf.showPage()
                    y = height - margin

                tx_date = tx['created_at'][:16] if tx['created_at'] else ""
                tx_type = "Yükleme" if tx['action_type'] == 'load' else "Harcama"
                tx_amount = float(tx['amount']) if tx['action_type'] == 'load' else abs(float(tx['amount']))
                amount_str = f"{tx_amount:,.2f} TL"

                pdf.drawString(x_positions[0] + 0.2*cm, y - 0.15*cm, tx_date)
                pdf.drawString(x_positions[1] + 0.2*cm, y - 0.15*cm, tx.get('cashier_name', '')[:20])
                pdf.drawString(x_positions[2] + 0.2*cm, y - 0.15*cm, tx_type)
                pdf.drawString(x_positions[3] + 0.2*cm, y - 0.15*cm, tx.get('note', '')[:35])
                pdf.drawRightString(x_positions[4] + col_widths[4] - 0.2*cm, y - 0.15*cm, amount_str)
                y -= 0.35 * cm

            y -= 0.3 * cm

        # Sales section
        if report["sales"]:
            if y < margin + 5*cm:
                pdf.showPage()
                y = height - margin

            pdf.setFont(bold_font, 12)
            pdf.setFillColor(accent_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
            pdf.setFillColor(white)
            pdf.drawString(margin + 0.3*cm, y - 0.15*cm, "SATIŞ DETAYLARI")
            y -= 0.8 * cm

            for sale in report["sales"][:30]:  # Limit to 30 sales
                if y < margin + 3*cm:
                    pdf.showPage()
                    y = height - margin

                # Sale header
                sale_date = sale['created_at'][:16] if sale['created_at'] else ""
                pdf.setFont(bold_font, 9)
                pdf.setFillColor(light_bg)
                pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.5*cm, fill=1, stroke=1)
                pdf.setFillColor(black)
                pdf.drawString(margin + 0.2*cm, y - 0.15*cm, f"{sale_date} | {sale.get('payment_method', 'Nakit')} | Kasa: {sale.get('cashier_name', '')}")
                pdf.drawRightString(width - margin - 0.2*cm, y - 0.15*cm, f"{float(sale['total']):,.2f} TL")
                y -= 0.6 * cm

                # Sale items
                items = report["sale_items"].get(sale["id"], [])
                if items:
                    pdf.setFont(regular_font, 8)
                    for item in items:
                        if y < margin + 1*cm:
                            pdf.showPage()
                            y = height - margin

                        item_text = f"  - {item['product_name']} x{item['quantity']} @ {float(item['unit_price']):,.2f} TL = {float(item['line_total']):,.2f} TL"
                        pdf.drawString(margin + 0.5*cm, y - 0.15*cm, item_text[:80])
                        y -= 0.3 * cm

                y -= 0.2 * cm

        # Footer
        pdf.setFont(italic_font, 8)
        pdf.setFillColor(HexColor("#666666"))
        pdf.drawString(margin, margin - 0.5*cm, f"Rapor Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')} | Matadors Club Kasa Sistemi")

        pdf.save()
        self.archive_report_to_drive(path, "musteri")
        return path

    @measure("pdf_olusturma_suresi", lambda self, report_date, cashier_id: f"daily_customers date={report_date} cashier_id={cashier_id}")
    def create_daily_customers_pdf(self, report_date: str, cashier_id: int | None):
        """Generate single-page PDF showing all customers with activity on a specific date.
        
        Shows GIRIS (yukleme) and CIKIS (harcama) totals for each customer on one page.
        
        Args:
            report_date: Date string "YYYY-MM-DD"
            cashier_id: If None (admin), shows all cashiers. If set, filters by that cashier.
        """
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.pdfgen import canvas
            from reportlab.lib.colors import HexColor, white, black
            from reportlab.lib.units import cm
        except ImportError as e:
            raise ImportError(f"PDF kütüphanesi yüklenemedi: {e}")

        try:
            report = self.db.daily_customers_summary(report_date, cashier_id=cashier_id)
        except Exception as e:
            raise RuntimeError(f"Veri alınırken hata: {e}")

        # Ensure reports directory exists
        report_dir = os.path.abspath(self._report_month_dir_for_cashier(cashier_id, report_date))
        try:
            os.makedirs(report_dir, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Rapor klasörü oluşturulamadı ({report_dir}): {e}")

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        scope = "tum_kasalar" if cashier_id is None else f"kasa_{cashier_id}"
        file_name = f"gunluk_musteri_ozeti_{report_date}_{scope}_{date_str}.pdf"
        path = os.path.join(report_dir, file_name)

        try:
            pdf = canvas.Canvas(path, pagesize=landscape(A4))
            regular_font, bold_font, italic_font = get_pdf_fonts(self.base_dir)
        except Exception as e:
            raise RuntimeError(f"PDF oluşturulamadı ({path}): {e}")

        width, height = landscape(A4)
        margin = 1.2 * cm

        # Colors
        header_bg = HexColor("#8B0000")  # Dark red
        text_color = black
        light_bg = HexColor("#F5F5F5")
        accent_bg = HexColor("#2C3E50")
        in_color = HexColor("#27AE60")  # Green for income
        out_color = HexColor("#E74C3C")   # Red for expense

        y = height - margin

        summary = report["summary"]
        customers = report["customers"]

        # Title
        pdf.setFont(bold_font, 18)
        pdf.setFillColor(header_bg)
        pdf.drawString(margin, y, f"Günlük Müşteri Hareket Özeti - {report_date}")
        y -= 0.8 * cm

        # Scope info
        pdf.setFont(regular_font, 10)
        pdf.setFillColor(black)
        if cashier_id is None:
            pdf.drawString(margin, y, "Kapsam: Tüm Kasalar")
        else:
            # Get cashier name
            cashier = self.db.get_user_by_id(cashier_id)
            cashier_name = cashier.get("full_name", cashier.get("username", "Kasa")) if cashier else "Kasa"
            pdf.drawString(margin, y, f"Kapsam: {cashier_name}")
        y -= 0.6 * cm

        # Summary box
        pdf.setFont(bold_font, 11)
        pdf.setFillColor(accent_bg)
        pdf.rect(margin, y - 0.35*cm, width - 2*margin, 0.55*cm, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.drawString(margin + 0.3*cm, y - 0.12*cm, 
            f"Toplam: {summary['total_customers']} müşteri | {summary['total_transactions']} işlem | "
            f"Giriş: {summary['grand_yukleme']:,.2f} TL | Çıkış: {summary['grand_harcama']:,.2f} TL | "
            f"Net: {summary['net_movement']:,.2f} TL")
        y -= 0.9 * cm

        # Table header
        col_widths = [1.2*cm, 6*cm, 3.5*cm, 3*cm, 3*cm, 3.5*cm, 3.5*cm]
        headers = ["No", "Müşteri", "Telefon", "Giriş (TL)", "Çıkış (TL)", "Net (TL)", "Bakiye (TL)"]
        x_positions = [margin]
        for w in col_widths[:-1]:
            x_positions.append(x_positions[-1] + w)

        pdf.setFillColor(light_bg)
        pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.55*cm, fill=1, stroke=1)
        pdf.setFillColor(black)
        pdf.setFont(bold_font, 9)
        for i, h in enumerate(headers):
            pdf.drawString(x_positions[i] + 0.2*cm, y - 0.15*cm, h)
        y -= 0.7 * cm

        # Customer rows
        pdf.setFont(regular_font, 8)
        row_height = 0.4 * cm
        
        for idx, c in enumerate(customers, 1):
            if y < margin + 1.5*cm:
                pdf.showPage()
                y = height - margin
                # Redraw header on new page
                pdf.setFillColor(light_bg)
                pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.55*cm, fill=1, stroke=1)
                pdf.setFillColor(black)
                pdf.setFont(bold_font, 9)
                for i, h in enumerate(headers):
                    pdf.drawString(x_positions[i] + 0.2*cm, y - 0.15*cm, h)
                y -= 0.7 * cm
                pdf.setFont(regular_font, 8)

            # Alternate row colors
            if idx % 2 == 0:
                pdf.setFillColor(HexColor("#FAFAFA"))
                pdf.rect(margin, y - 0.35*cm, width - 2*margin, row_height, fill=1, stroke=0)

            pdf.setFillColor(black)
            
            # Data
            net = c['yukleme_total'] - c['harcama_total']
            
            pdf.drawString(x_positions[0] + 0.2*cm, y - 0.25*cm, str(idx))
            pdf.drawString(x_positions[1] + 0.2*cm, y - 0.25*cm, c['name'][:30])
            pdf.drawString(x_positions[2] + 0.2*cm, y - 0.25*cm, c['phone'][:15])
            
            # Giris (Green)
            pdf.setFillColor(in_color)
            pdf.drawRightString(x_positions[3] + col_widths[3] - 0.2*cm, y - 0.25*cm, f"{c['yukleme_total']:,.2f}")
            
            # Cikis (Red)
            pdf.setFillColor(out_color)
            pdf.drawRightString(x_positions[4] + col_widths[4] - 0.2*cm, y - 0.25*cm, f"{c['harcama_total']:,.2f}")
            
            # Net (Black, bold if negative)
            pdf.setFillColor(black)
            if net < 0:
                pdf.setFont(bold_font, 8)
            pdf.drawRightString(x_positions[5] + col_widths[5] - 0.2*cm, y - 0.25*cm, f"{net:,.2f}")
            pdf.setFont(regular_font, 8)
            
            # Current Balance
            pdf.drawRightString(x_positions[6] + col_widths[6] - 0.2*cm, y - 0.25*cm, f"{c['current_balance']:,.2f}")
            
            y -= row_height

        # Footer line
        y -= 0.3 * cm
        pdf.setFillColor(HexColor("#CCCCCC"))
        pdf.rect(margin, y, width - 2*margin, 0.05*cm, fill=1, stroke=0)
        
        y -= 0.5 * cm
        pdf.setFont(italic_font, 8)
        pdf.setFillColor(HexColor("#666666"))
        pdf.drawString(margin, y, f"Rapor Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')} | Matadors Club Kasa Sistemi")

        pdf.save()
        self.archive_report_to_drive(path, "musteri")
        return path

    @measure("pdf_olusturma_suresi", lambda self, report_date, cashier_id: f"defter_daily date={report_date} cashier_id={cashier_id}")
    def create_defter_daily_pdf(self, report_date: str, cashier_id: int | None):
        """Generate PDF for daily DEFTER (credit) sales report.
        
        Shows all customers who made DEFTER purchases on the specified date
        with their transaction details.
        """
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.pdfgen import canvas
            from reportlab.lib.colors import HexColor, white, black
            from reportlab.lib.units import cm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError as e:
            raise ImportError(f"PDF kütüphanesi yüklenemedi: {e}")

        try:
            report = self.db.defter_report(report_date, cashier_id=cashier_id)
        except Exception as e:
            raise RuntimeError(f"Veri alınırken hata: {e}")

        report_dir = os.path.abspath(self._report_month_dir_for_cashier(cashier_id, report_date))
        try:
            os.makedirs(report_dir, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Rapor klasörü oluşturulamadı: {e}")

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        scope = "tum_kasalar" if cashier_id is None else f"kasa_{cashier_id}"
        file_name = f"defter_gunluk_{report_date}_{scope}_{date_str}.pdf"
        path = os.path.join(report_dir, file_name)

        try:
            pdf = canvas.Canvas(path, pagesize=landscape(A4))
        except Exception as e:
            raise RuntimeError(f"PDF oluşturulamadı: {e}")

        # Register Turkish font with caching for better performance
        import sys
        regular_font, bold_font, italic_font = get_pdf_fonts(self.base_dir)
        
        # Cache font registration to avoid repeated operations
        if not hasattr(self, '_font_cache'):
            self._font_cache = {}
        
        cache_key = f"turkish_font_{sys.platform}"
        if cache_key not in self._font_cache:
            if sys.platform == 'win32':
                try:
                    # Try to register Arial from Windows fonts directory
                    arial_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arial.ttf')
                    if os.path.exists(arial_path):
                        pdfmetrics.registerFont(TTFont('TurkishRegular', arial_path))
                        pdfmetrics.registerFont(TTFont('TurkishBold', os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arialbd.ttf')))
                        regular_font = 'TurkishRegular'
                        bold_font = 'TurkishBold'
                        self._font_cache[cache_key] = (regular_font, bold_font)
                    else:
                        # Try Calibri as fallback
                        calibri_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'calibri.ttf')
                        if os.path.exists(calibri_path):
                            pdfmetrics.registerFont(TTFont('TurkishRegular', calibri_path))
                            pdfmetrics.registerFont(TTFont('TurkishBold', os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'calibrib.ttf')))
                            regular_font = 'TurkishRegular'
                            bold_font = 'TurkishBold'
                            self._font_cache[cache_key] = (regular_font, bold_font)
                except Exception:
                    self._font_cache[cache_key] = (regular_font, bold_font)
        else:
            regular_font, bold_font = self._font_cache[cache_key]
        
        # Set PDF encoding to support Turkish characters
        pdf.setTitle("DEFTER Raporu")
        pdf.setAuthor("Matadors Club Kasa Sistemi")

        width, height = landscape(A4)
        margin = 1.2 * cm

        header_bg = HexColor("#2C3E50")
        defter_color = HexColor("#E74C3C")  # Red for DEFTER
        light_bg = HexColor("#F5F5F5")
        accent_bg = HexColor("#34495E")

        y = height - margin

        customers = report["customers"]
        summary = report["summary"]

        # Title
        pdf.setFont(bold_font, 18)
        pdf.setFillColor(defter_color)
        pdf.drawString(margin, y, f"DEFTER Günlük Raporu - {report_date}")
        y -= 0.8 * cm

        # Scope info
        pdf.setFont(regular_font, 10)
        pdf.setFillColor(black)
        if cashier_id is None:
            pdf.drawString(margin, y, "Kapsam: Tüm Kasalar")
        else:
            cashier = self.db.get_user_by_id(cashier_id)
            cashier_name = cashier.get("full_name", "Kasa") if cashier else "Kasa"
            pdf.drawString(margin, y, f"Kapsam: {cashier_name}")
        y -= 0.6 * cm

        # Summary box
        pdf.setFont(bold_font, 11)
        pdf.setFillColor(accent_bg)
        pdf.rect(margin, y - 0.35*cm, width - 2*margin, 0.55*cm, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.drawString(margin + 0.3*cm, y - 0.12*cm,
            f"Toplam: {summary['total_customers']} müşteri | {summary['total_transactions']} satış | "
            f"Defter Tutar: {summary['total_defter_sales']:,.2f} TL")
        y -= 0.9 * cm

        # Customer details
        for customer in customers:
            if y < margin + 4*cm:
                pdf.showPage()
                y = height - margin

            # Customer header with colored dot
            pdf.setFont(bold_font, 10)
            pdf.setFillColor(header_bg)
            pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
            
            # Determine balance color dot
            balance = customer['customer_balance']
            if balance < 0:
                dot_color = HexColor("#E74C3C")  # Red for negative
                dot_text = "●"
            elif balance > 0:
                dot_color = HexColor("#27AE60")  # Green for positive
                dot_text = "●"
            else:
                dot_color = HexColor("#F39C12")  # Orange for zero
                dot_text = "●"
            
            is_test = False
            test_indicator = "🧪 " if is_test else ""
            
            pdf.setFillColor(white)
            # Draw colored dot
            pdf.setFillColor(dot_color)
            pdf.drawString(margin + 0.3*cm, y - 0.15*cm, dot_text)
            
            # Draw customer info with colored name
            pdf.setFillColor(HexColor("#3498DB"))  # Blue for customer names
            customer_text = f"{test_indicator}{customer['customer_name']}"
            pdf.drawString(margin + 0.6*cm, y - 0.15*cm, customer_text)
            
            # Draw other info in white
            pdf.setFillColor(white)
            info_text = f"| Tel: {customer['customer_phone'] or '-'} | Bakiye: {customer['customer_balance']:,.2f} TL | Limit: {customer['customer_credit_limit']:,.2f} TL"
            pdf.drawString(margin + 0.6*cm + pdf.stringWidth(customer_text, bold_font, 10), y - 0.15*cm, info_text)
            y -= 0.8 * cm

            # Sales table header
            col_widths = [3*cm, 8*cm, 3*cm, 4*cm]
            headers = ["Saat", "Ürünler", "Tutar", "Kasa"]
            x_positions = [margin]
            for w in col_widths[:-1]:
                x_positions.append(x_positions[-1] + w)

            pdf.setFillColor(light_bg)
            pdf.rect(margin, y - 0.35*cm, width - 2*margin, 0.5*cm, fill=1, stroke=1)
            pdf.setFillColor(black)
            pdf.setFont(bold_font, 8)
            for i, h in enumerate(headers):
                pdf.drawString(x_positions[i] + 0.2*cm, y - 0.15*cm, h)
            y -= 0.6 * cm

            # Sales rows
            pdf.setFont(regular_font, 8)
            for sale in customer['sales']:
                if y < margin + 1*cm:
                    pdf.showPage()
                    y = height - margin

                saat = sale['created_at'][11:16] if sale['created_at'] else ""
                # Use product names instead of IDs - items already have product_name from database
                items_str = ", ".join([f"{i['product_name']}x{i['quantity']}" for i in sale['items'][:3]])
                if len(sale['items']) > 3:
                    items_str += "..."

                pdf.drawString(x_positions[0] + 0.2*cm, y - 0.25*cm, saat)
                pdf.drawString(x_positions[1] + 0.2*cm, y - 0.25*cm, items_str[:40])
                pdf.drawRightString(x_positions[2] + col_widths[2] - 0.2*cm, y - 0.25*cm, f"{float(sale['total']):,.2f}")
                pdf.drawString(x_positions[3] + 0.2*cm, y - 0.25*cm, sale.get('cashier_name', '')[:15])
                y -= 0.35 * cm

            # Customer total
            pdf.setFont(bold_font, 8)
            pdf.setFillColor(defter_color)
            pdf.drawRightString(width - margin - 0.5*cm, y - 0.25*cm,
                f"Müşteri Toplam: {customer['total_amount']:,.2f} TL")
            pdf.setFillColor(black)
            y -= 0.6 * cm

        # Footer
        pdf.setFont(regular_font, 8)
        pdf.setFillColor(HexColor("#666666"))
        pdf.drawString(margin, margin - 0.5*cm,
            f"Rapor Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')} | Matadors Club Kasa Sistemi")

        pdf.save()
        self.archive_report_to_drive(path, "defter_gunluk")
        return path

    @measure("pdf_olusturma_suresi", lambda self, cashier_id, report_date=None: f"defter_balance cashier_id={cashier_id} date={report_date or ''}")
    def create_defter_balance_pdf(self, cashier_id: int | None, report_date: str | None = None):
        """Generate PDF for DEFTER customers balance report.
        
        Shows all customers with their current balance and credit status.
        """
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.pdfgen import canvas
            from reportlab.lib.colors import HexColor, white, black
            from reportlab.lib.units import cm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError as e:
            raise ImportError(f"PDF kütüphanesi yüklenemedi: {e}")

        try:
            report = self.db.defter_customers_balance_report(cashier_id=cashier_id, active_only=True)
        except Exception as e:
            raise RuntimeError(f"Veri alınırken hata: {e}")

        report_date = report_date or business_day()
        report_dir = os.path.abspath(self._report_month_dir_for_cashier(cashier_id, report_date))
        try:
            os.makedirs(report_dir, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Rapor klasörü oluşturulamadı: {e}")

        scope = "tum_kasalar" if cashier_id is None else f"kasa_{cashier_id}"
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"defter_bakiye_ozeti_{report_date}_{scope}_{date_str}.pdf"
        path = os.path.join(report_dir, file_name)

        try:
            pdf = canvas.Canvas(path, pagesize=landscape(A4))
        except Exception as e:
            raise RuntimeError(f"PDF oluşturulamadı: {e}")

        # Register Turkish font with proper encoding
        import sys
        regular_font, bold_font, italic_font = get_pdf_fonts(self.base_dir)
        
        if sys.platform == 'win32':
            try:
                # Try to register Arial from Windows fonts directory
                arial_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arial.ttf')
                if os.path.exists(arial_path):
                    pdfmetrics.registerFont(TTFont('TurkishRegular', arial_path))
                    pdfmetrics.registerFont(TTFont('TurkishBold', os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arialbd.ttf')))
                    regular_font = 'TurkishRegular'
                    bold_font = 'TurkishBold'
                else:
                    # Try Calibri as fallback
                    calibri_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'calibri.ttf')
                    if os.path.exists(calibri_path):
                        pdfmetrics.registerFont(TTFont('TurkishRegular', calibri_path))
                        pdfmetrics.registerFont(TTFont('TurkishBold', os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'calibrib.ttf')))
                        regular_font = 'TurkishRegular'
                        bold_font = 'TurkishBold'
            except Exception:
                pass  # Fall back to Helvetica
        
        # Set PDF encoding to support Turkish characters
        pdf.setTitle("DEFTER Özet")
        pdf.setAuthor("Matadors Club Kasa Sistemi")

        width, height = landscape(A4)
        margin = 1.2 * cm

        header_bg = HexColor("#2C3E50")
        negative_color = HexColor("#E74C3C")  # Red for negative balance
        positive_color = HexColor("#27AE60")  # Green for positive balance
        light_bg = HexColor("#F5F5F5")
        accent_bg = HexColor("#34495E")

        y = height - margin

        customers = report["customers"]
        summary = report["summary"]

        # Title
        pdf.setFont(bold_font, 18)
        pdf.setFillColor(header_bg)
        pdf.drawString(margin, y, "DEFTER Özet")
        y -= 0.8 * cm

        # Date and scope
        pdf.setFont(regular_font, 10)
        pdf.setFillColor(black)
        pdf.drawString(margin, y, f"Tarih: {datetime.now().strftime('%d.%m.%Y')}")
        if cashier_id is None:
            pdf.drawString(margin + 8*cm, y, "Kapsam: Tüm Kasalar")
        else:
            cashier = self.db.get_user_by_id(cashier_id)
            cashier_name = cashier.get("full_name", "Kasa") if cashier else "Kasa"
            pdf.drawString(margin + 8*cm, y, f"Kapsam: {cashier_name}")
        y -= 0.6 * cm

        # Summary box
        pdf.setFont(bold_font, 10)
        pdf.setFillColor(accent_bg)
        pdf.rect(margin, y - 0.35*cm, width - 2*margin, 0.55*cm, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.drawString(margin + 0.3*cm, y - 0.12*cm,
            f"Toplam: {summary['total_customers']} müşteri | "
            f"Toplam Bakiye: {summary['total_balance']:,.2f} TL | "
            f"Kullanılan Kredi: {summary['total_credit_used']:,.2f} TL | "
            f"Toplam Defter Alışveriş: {summary['total_defter_purchases']:,.2f} TL")
        y -= 0.9 * cm

        # Table header
        col_widths = [1*cm, 5*cm, 3*cm, 3*cm, 3*cm, 3.5*cm, 3.5*cm, 3*cm]
        headers = ["No", "Müşteri", "Telefon", "Bakiye", "Kredi Limit", "Kullanılan", "Toplam Defter", "Son İşlem"]
        x_positions = [margin]
        for w in col_widths[:-1]:
            x_positions.append(x_positions[-1] + w)

        pdf.setFillColor(light_bg)
        pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.55*cm, fill=1, stroke=1)
        pdf.setFillColor(black)
        pdf.setFont(bold_font, 8)
        for i, h in enumerate(headers):
            pdf.drawString(x_positions[i] + 0.15*cm, y - 0.2*cm, h)
        y -= 0.7 * cm

        # Customer rows
        pdf.setFont(regular_font, 8)
        row_height = 0.4 * cm

        for idx, c in enumerate(customers, 1):
            if y < margin + 1.5*cm:
                pdf.showPage()
                y = height - margin
                # Redraw header
                pdf.setFillColor(light_bg)
                pdf.rect(margin, y - 0.4*cm, width - 2*margin, 0.55*cm, fill=1, stroke=1)
                pdf.setFillColor(black)
                pdf.setFont(bold_font, 8)
                for i, h in enumerate(headers):
                    pdf.drawString(x_positions[i] + 0.15*cm, y - 0.2*cm, h)
                y -= 0.7 * cm
                pdf.setFont(regular_font, 8)

            # Alternate row colors
            if idx % 2 == 0:
                pdf.setFillColor(HexColor("#FAFAFA"))
                pdf.rect(margin, y - 0.35*cm, width - 2*margin, row_height, fill=1, stroke=0)

            # Balance color and dot
            balance = c['balance']
            if balance < 0:
                dot_color = HexColor("#E74C3C")  # Red for negative
                dot_text = "●"
            elif balance > 0:
                dot_color = HexColor("#27AE60")  # Green for positive
                dot_text = "●"
            else:
                dot_color = HexColor("#F39C12")  # Orange for zero
                dot_text = "●"

            is_test = False
            test_indicator = "🧪 " if is_test else ""

            pdf.drawString(x_positions[0] + 0.15*cm, y - 0.25*cm, str(idx))
            
            # Draw colored dot
            pdf.setFillColor(dot_color)
            pdf.drawString(x_positions[1] + 0.15*cm, y - 0.25*cm, dot_text)
            
            # Draw customer name with color
            pdf.setFillColor(HexColor("#3498DB"))  # Blue for customer names
            customer_text = f"{test_indicator}{c['name'][:22]}"
            pdf.drawString(x_positions[1] + 0.5*cm, y - 0.25*cm, customer_text)
            
            # Draw phone in black
            pdf.setFillColor(black)
            pdf.drawString(x_positions[2] + 0.15*cm, y - 0.25*cm, c['phone'][:12])

            # Balance (colored)
            pdf.drawRightString(x_positions[3] + col_widths[3] - 0.15*cm, y - 0.25*cm, f"{balance:,.2f}")

            # Other columns in black
            pdf.setFillColor(black)
            pdf.drawRightString(x_positions[4] + col_widths[4] - 0.15*cm, y - 0.25*cm, f"{c['credit_limit']:,.2f}")
            pdf.drawRightString(x_positions[5] + col_widths[5] - 0.15*cm, y - 0.25*cm, f"{c['credit_used']:,.2f}")
            pdf.drawRightString(x_positions[6] + col_widths[6] - 0.15*cm, y - 0.25*cm, f"{c['total_defter_purchases']:,.2f}")
            pdf.drawString(x_positions[7] + 0.15*cm, y - 0.25*cm, c['last_defter_date'][:10])

            y -= row_height

        # Footer
        pdf.setFont(regular_font, 8)
        pdf.setFillColor(HexColor("#666666"))
        pdf.drawString(margin, margin - 0.5*cm,
            f"Rapor Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')} | Matadors Club Kasa Sistemi")

        pdf.save()
        self.archive_report_to_drive(path, "stok_defter")
        return path
