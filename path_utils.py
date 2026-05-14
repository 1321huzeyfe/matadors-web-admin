# -*- coding: utf-8 -*-
"""
Safe path management for PyInstaller bundled applications.

Bundled resources and writable application data are intentionally separate:
resources are read from PyInstaller's temporary bundle when frozen, while
database, reports, backups and exports live in a single writable data folder.
"""
import sys
import os
import re
from datetime import datetime, time, timedelta
from pathlib import Path


DB_FILE_NAME = "manager.db"
AUTH_DB_FILE_NAME = "matadors_kasa_auth.db"
BUSINESS_DAY_CUTOFF = time(23, 30)
APP_DATA_ENV = "MATADORSAPP_DATA_DIR"


def get_app_root():
    """Return the read-only program/resource directory that owns the app/exe."""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent)
    return os.path.dirname(os.path.abspath(__file__))


def get_user_data_root() -> Path:
    """Return the writable data root, intentionally outside the program folder."""
    override = os.environ.get(APP_DATA_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "MatadorsApp_Data"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "MatadorsApp" / "MatadorsApp_Data"
        return Path.home() / "AppData" / "Local" / "MatadorsApp" / "MatadorsApp_Data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MatadorsApp" / "MatadorsApp_Data"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "MatadorsApp" / "MatadorsApp_Data"

def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller
    
    Args:
        relative_path (str): Relative path to the resource
        
    Returns:
        str: Absolute path to the resource
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = get_app_root()
    
    return os.path.join(base_path, relative_path)

def get_customtkinter_assets_path():
    """
    Get the path to customtkinter assets directory
    
    Returns:
        str: Path to customtkinter assets directory
    """
    return resource_path("customtkinter/assets")

def get_app_assets_path():
    """
    Get the path to application assets directory
    
    Returns:
        str: Path to application assets directory
    """
    return resource_path("assets")

def ensure_path_exists(path):
    """
    Ensure a directory exists, create if it doesn't
    
    Args:
        path (str): Directory path to ensure exists
    """
    os.makedirs(path, exist_ok=True)
    return path


def get_data_dir():
    """Return the writable data root; never place live data in the program folder."""
    return str(ensure_path_exists(get_user_data_root()))


def get_desktop_dir() -> Path:
    """Return the user's Desktop folder with a conservative fallback."""
    desktop = Path.home() / "Desktop"
    return desktop if desktop.exists() else Path.home()


def get_pdf_reports_dir() -> Path:
    """Return the single user-facing PDF report folder."""
    return Path(ensure_path_exists(get_desktop_dir() / "MatadorsApp_Raporlar"))


def sanitize_kasa_name(kasa_adi: str) -> str:
    """Normalize a kasa/profile name for folder paths."""
    value = (kasa_adi or "").strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "_", value)
    return value or "kasa"


def _data_root(data_root=None) -> Path:
    return Path(data_root) if data_root is not None else Path(get_data_dir())


def get_local_root(data_root=None) -> Path:
    """Return the standard local profile data root."""
    return Path(ensure_path_exists(_data_root(data_root) / "local"))


def get_local_dir():
    """Compatibility alias for older code; manager DB lives in local/manager/db."""
    return str(get_kasa_db_dir("manager"))


def get_drive_sync_dir():
    """Return the default local Google Drive sync mirror directory."""
    return ensure_path_exists(os.path.join(get_data_dir(), "drive_sync"))


def get_drive_sync_root(data_root=None) -> Path:
    return Path(ensure_path_exists(_data_root(data_root) / "drive_sync"))


def get_drive_kasa_dir(kasa_adi: str, data_root=None) -> Path:
    return Path(ensure_path_exists(get_drive_sync_root(data_root) / sanitize_kasa_name(kasa_adi)))


def get_drive_kasa_db_path(kasa_adi: str, data_root=None) -> Path:
    return get_drive_kasa_dir(kasa_adi, data_root) / "sales.db"


def get_drive_kasa_customers_db_path(kasa_adi: str, data_root=None) -> Path:
    return get_drive_kasa_dir(kasa_adi, data_root) / "customers.db"


def get_drive_kasa_stock_db_path(kasa_adi: str, data_root=None) -> Path:
    return get_drive_kasa_dir(kasa_adi, data_root) / "stock.db"


def get_drive_kasa_reports_dir(kasa_adi: str, data_root=None) -> Path:
    return Path(ensure_path_exists(get_drive_kasa_dir(kasa_adi, data_root) / "reports"))


def get_drive_backups_dir(data_root=None) -> Path:
    return Path(ensure_path_exists(get_drive_sync_root(data_root) / "backups"))


def get_drive_manager_cache_dir(data_root=None) -> Path:
    return Path(ensure_path_exists(get_drive_sync_root(data_root) / "manager_cache"))


def get_drive_backup_month_dir(day: str | None = None, data_root=None) -> Path:
    return Path(ensure_path_exists(get_drive_backups_dir(data_root) / business_month(day)))


def get_drive_daily_backup_path(kasa_adi: str, filename: str = "sales", day: str | None = None, data_root=None) -> Path:
    selected_day = day or business_day()
    return get_drive_backup_month_dir(selected_day, data_root) / f"{sanitize_kasa_name(kasa_adi)}_{filename}_{selected_day}.db"


def get_drive_kasa_status_path(kasa_adi: str, data_root=None) -> Path:
    return get_drive_kasa_dir(kasa_adi, data_root) / "sync_status.json"


def get_drive_kasa_lock_path(kasa_adi: str, data_root=None) -> Path:
    return get_drive_kasa_dir(kasa_adi, data_root) / ".sync.lock"


def get_drive_kasa_log_path(kasa_adi: str, data_root=None) -> Path:
    return get_kasa_logs_dir(kasa_adi, data_root) / "drive_sync.log"


def get_admin_panel_dir(drive_root=None, data_root=None) -> Path:
    root = Path(drive_root) if drive_root is not None else get_drive_sync_root(data_root)
    return Path(ensure_path_exists(root / "admin_panel"))


def get_admin_panel_cashiers_dir(drive_root=None, data_root=None) -> Path:
    return Path(ensure_path_exists(get_admin_panel_dir(drive_root, data_root) / "kasalar"))


def get_admin_dashboard_path(drive_root=None, data_root=None) -> Path:
    return get_admin_panel_dir(drive_root, data_root) / "dashboard.json"


def get_admin_cashier_summary_path(kasa_adi: str, drive_root=None, data_root=None) -> Path:
    return get_admin_panel_cashiers_dir(drive_root, data_root) / f"{sanitize_kasa_name(kasa_adi)}.json"


def get_kasalar_dir():
    """Compatibility alias for the per-profile local data root."""
    return str(get_local_root())


def get_kasa_dir(kasa_adi: str, data_root=None) -> Path:
    return Path(ensure_path_exists(get_local_root(data_root) / sanitize_kasa_name(kasa_adi)))


def get_kasa_db_dir(kasa_adi: str, data_root=None) -> Path:
    return Path(ensure_path_exists(get_kasa_dir(kasa_adi, data_root) / "db"))


def get_kasa_reports_dir(kasa_adi: str, data_root=None) -> Path:
    return get_pdf_reports_dir()


def get_kasa_backups_dir(kasa_adi: str, data_root=None) -> Path:
    return Path(ensure_path_exists(_data_root(data_root) / "backups" / sanitize_kasa_name(kasa_adi)))


def get_kasa_logs_dir(kasa_adi: str, data_root=None) -> Path:
    return Path(ensure_path_exists(_data_root(data_root) / "logs" / sanitize_kasa_name(kasa_adi)))


def get_kasa_db_path(kasa_adi: str, filename: str = "sales.db", data_root=None) -> Path:
    return get_kasa_db_dir(kasa_adi, data_root) / filename


def get_kasa_customers_json_path(kasa_adi: str, data_root=None) -> Path:
    return get_kasa_db_dir(kasa_adi, data_root) / "customers.json"


def get_kasa_products_json_path(kasa_adi: str, data_root=None) -> Path:
    return get_kasa_db_dir(kasa_adi, data_root) / "products.json"


def get_kasa_transactions_json_path(kasa_adi: str, data_root=None) -> Path:
    return get_kasa_db_dir(kasa_adi, data_root) / "transactions.json"


def business_day(now: datetime | None = None) -> str:
    """Return the app business date; after 23:30 belongs to the next day."""
    current = now or datetime.now()
    day = current.date()
    if current.time() >= BUSINESS_DAY_CUTOFF:
        day += timedelta(days=1)
    return day.isoformat()


def business_month(day: str | None = None) -> str:
    return (day or business_day())[:7]


def get_kasa_daily_backup_path(kasa_adi: str, day: str | None = None, data_root=None) -> Path:
    return get_kasa_backups_dir(kasa_adi, data_root) / f"sales_{day or business_day()}.sqlite"


def get_kasa_report_month_dir(kasa_adi: str, day: str | None = None, data_root=None) -> Path:
    return get_pdf_reports_dir()


def get_reports_dir():
    """Compatibility alias; all PDF reports live on the Desktop."""
    return str(get_pdf_reports_dir())


def get_backups_dir():
    """Compatibility alias; manager backups live under backups/manager."""
    return str(get_kasa_backups_dir("manager"))


def get_logs_dir():
    """Return the single logs directory."""
    return ensure_path_exists(os.path.join(get_data_dir(), "logs"))


def get_exports_dir():
    """Compatibility alias; exports are kept in the PDF reports folder."""
    return get_reports_dir()


def ensure_standard_data_dirs():
    """Create the one supported writable layout."""
    for path in (
        get_local_root(),
        _data_root() / "backups",
        get_logs_dir(),
        get_kasa_db_dir("manager"),
        get_kasa_backups_dir("manager"),
        get_kasa_logs_dir("manager"),
    ):
        ensure_path_exists(path)


def get_db_path():
    return str(get_kasa_db_path("manager", DB_FILE_NAME))


def get_auth_db_path():
    return str(get_kasa_db_path("manager", AUTH_DB_FILE_NAME))
