# -*- coding: utf-8 -*-
"""Profile and configurable path management for local multi-kasa usage."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from path_utils import (
    get_data_dir,
    get_drive_kasa_dir,
    get_drive_kasa_reports_dir,
    get_local_root,
    get_kasa_backups_dir,
    get_kasa_customers_json_path,
    get_kasa_db_path,
    get_kasa_dir,
    get_kasa_logs_dir,
    get_kasa_products_json_path,
    get_kasa_reports_dir,
    get_kasa_transactions_json_path,
    sanitize_kasa_name,
)


PROFILE_KASA = "kasa"
PROFILE_MANAGER = "yonetici"


@dataclass(frozen=True)
class Profile:
    username: str
    profile_type: str
    local_db_path: Path
    drive_dir: Path
    kasa_dir: Path | None = None

    @property
    def drive_db_path(self) -> Path:
        return self.drive_dir / "sales.db"

    @property
    def reports_dir(self) -> Path:
        return self.kasa_reports_dir

    @property
    def backups_dir(self) -> Path:
        return self.kasa_backups_dir

    @property
    def customers_json_path(self) -> Path:
        return get_kasa_customers_json_path(self.username, self._data_root)

    @property
    def transactions_json_path(self) -> Path:
        return get_kasa_transactions_json_path(self.username, self._data_root)

    @property
    def products_json_path(self) -> Path:
        return get_kasa_products_json_path(self.username, self._data_root)

    @property
    def kasa_backups_dir(self) -> Path:
        return get_kasa_backups_dir(self.username, self._data_root)

    @property
    def kasa_reports_dir(self) -> Path:
        return get_kasa_reports_dir(self.username, self._data_root)

    @property
    def kasa_logs_dir(self) -> Path:
        return get_kasa_logs_dir(self.username, self._data_root)

    @property
    def kasa_db_dir(self) -> Path:
        return get_kasa_db_path(self.username, data_root=self._data_root).parent

    @property
    def _data_root(self) -> Path:
        if self.kasa_dir:
            return self.kasa_dir.parent.parent
        return self.drive_dir.parent.parent


class ProfileManager:
    """Owns the external data-root local/, drive_sync/, backups/, reports/ and logs/ layout."""

    def __init__(self, data_root: str | Path | None = None):
        self.data_root = Path(data_root or get_data_dir())
        self.local_dir = get_kasa_db_path("manager", "manager.db", self.data_root).parent
        self.backups_dir = get_kasa_backups_dir("manager", self.data_root)
        self.reports_dir = get_kasa_reports_dir("manager", self.data_root)
        self.logs_dir = self.data_root / "logs"
        self.kasalar_dir = get_local_root(self.data_root)
        self.config_path = self.data_root / "config.json"
        self._config = self._load_config()
        self.ensure_base_layout()

    def _google_drive_desktop_roots(self) -> list[Path]:
        roots: list[Path] = []
        home = Path.home()
        for candidate in (
            home / "Google Drive",
            home / "My Drive",
            home / "Drive'ım",
            home / "AppData" / "Local" / "Google" / "DriveFS",
        ):
            if candidate.exists():
                roots.append(candidate)
        for drive in "DEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{drive}:\\")
            if not root.exists():
                continue
            roots.append(root)
            for child_name in ("My Drive", "Drive'ım", "Google Drive", ".shortcut-targets-by-id"):
                child = root / child_name
                if child.exists():
                    roots.append(child)
        seen = set()
        unique = []
        for root in roots:
            key = str(root).casefold()
            if key not in seen:
                seen.add(key)
                unique.append(root)
        return unique

    def _looks_like_drive_root(self, root: Path) -> bool:
        if not root.exists() or not root.is_dir():
            return False
        try:
            if (root / "shared").exists() or (root / "backups").exists():
                return True
            return any((item / "sales.db").exists() for item in root.iterdir() if item.is_dir())
        except OSError:
            return False

    def _resolve_drive_root(self, configured: str) -> Path | None:
        value = (configured or "").strip()
        if not value:
            return None
        raw = Path(value).expanduser()
        if raw.is_absolute():
            return raw
        for root in self._google_drive_desktop_roots():
            candidate = root / value
            if self._looks_like_drive_root(candidate):
                return candidate.resolve()
        for candidate in (self.data_root / value,):
            if self._looks_like_drive_root(candidate):
                return candidate.resolve()
        return None

    def _load_config(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def save_config(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self._config, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_drive_root(self) -> Path:
        configured = str(self._config.get("drive_sync_root", "")).strip()
        resolved = self._resolve_drive_root(configured)
        if resolved is not None:
            return resolved
        return self.data_root / "drive_sync"

    def set_drive_root(self, folder: str | Path) -> Path:
        root = Path(folder).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self._config["drive_sync_root"] = str(root)
        self.save_config()
        self.ensure_base_layout()
        return root

    def ensure_base_layout(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.kasalar_dir.mkdir(parents=True, exist_ok=True)
        get_kasa_logs_dir("manager", self.data_root)
        return

    def profile_for_user(self, user: dict) -> Profile:
        username = self.sanitize_profile_name(user.get("username", "manager"))
        is_admin = user.get("user_type") == "admin"
        if is_admin:
            return Profile(
                username="manager",
                profile_type=PROFILE_MANAGER,
                local_db_path=get_kasa_db_path("manager", "manager.db", self.data_root),
                drive_dir=self.get_drive_root() / "manager",
                kasa_dir=get_kasa_dir("manager", self.data_root),
            )
        return self.ensure_cashier_profile(username)

    def ensure_cashier_profile(self, username: str) -> Profile:
        profile_name = self.sanitize_profile_name(username)
        local_db = get_kasa_db_path(profile_name, "sales.db", self.data_root)
        drive_dir = self.get_drive_root() / profile_name
        kasa_dir = get_kasa_dir(profile_name, self.data_root)
        for folder in (
            kasa_dir,
            get_kasa_db_path(profile_name, data_root=self.data_root).parent,
            get_kasa_backups_dir(profile_name, self.data_root),
            get_kasa_reports_dir(profile_name, self.data_root),
            get_kasa_logs_dir(profile_name, self.data_root),
        ):
            folder.mkdir(parents=True, exist_ok=True)
        for file_path in (
            get_kasa_customers_json_path(profile_name, self.data_root),
            get_kasa_transactions_json_path(profile_name, self.data_root),
            get_kasa_products_json_path(profile_name, self.data_root),
        ):
            if not file_path.exists():
                file_path.write_text("[]\n", encoding="utf-8")
        return Profile(profile_name, PROFILE_KASA, local_db, drive_dir, kasa_dir=kasa_dir)

    def rename_cashier_profile(self, old_username: str, new_username: str) -> Profile:
        """Rename an isolated cashier profile folder/database when username changes."""
        old_name = self.sanitize_profile_name(old_username)
        new_name = self.sanitize_profile_name(new_username)
        if not old_name or not new_name:
            raise ValueError("Kasa kullanici adi zorunlu.")
        if old_name == new_name:
            return self.ensure_cashier_profile(new_name)

        old_kasa_dir = self.data_root / "local" / old_name
        new_kasa_dir = self.data_root / "local" / new_name
        moves = [
            (old_kasa_dir, new_kasa_dir),
            (self.data_root / "backups" / old_name, self.data_root / "backups" / new_name),
            (self.data_root / "reports" / old_name, self.data_root / "reports" / new_name),
            (self.data_root / "logs" / old_name, self.data_root / "logs" / new_name),
            (self.get_drive_root() / old_name, self.get_drive_root() / new_name),
        ]
        for src, dst in moves:
            if src.exists() and dst.exists():
                raise ValueError(f"Yeni kasa yolu zaten var: {dst}")
        for src, dst in moves:
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        return self.ensure_cashier_profile(new_name)

    def cashier_profiles_from_users(self, users: list[dict]) -> list[Profile]:
        return [self.ensure_cashier_profile(u["username"]) for u in users if u.get("user_type") == "cashier"]

    def read_drive_root_setting(self) -> str:
        return str(self.get_drive_root())

    @staticmethod
    def sanitize_profile_name(username: str) -> str:
        return sanitize_kasa_name(username)
