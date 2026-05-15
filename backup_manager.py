# -*- coding: utf-8 -*-
"""Safe local and sync-folder backups for the Matadors SQLite database."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import traceback
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from path_utils import business_day, business_month
from safe_io import atomic_copy_file, atomic_write_json, fsync_parent, sqlite_online_backup
from performance import measure


class BackupError(RuntimeError):
    """Raised when a backup or restore operation cannot be completed safely."""


@dataclass
class BackupResult:
    ok: bool
    status: str
    message: str
    local_path: str = ""
    drive_path: str = ""
    checksum: str = ""
    error: str = ""


class BackupManager:
    """Create verified SQLite backups without changing the live database flow."""

    BACKUP_INTERVAL = timedelta(minutes=10)

    def __init__(self, db_path: str, settings_db, base_dir: str):
        self.db_path = Path(db_path)
        self.settings_db = settings_db
        self.base_dir = Path(base_dir)
        self.backup_root = self._resolve_backup_root()
        self.local_root = self.backup_root
        self.emergency_root = self.backup_root / "emergency"
        self.log_path = self._resolve_log_path()
        self._backup_list_cache: tuple[float, list[dict[str, str]]] | None = None

    def _resolve_backup_root(self) -> Path:
        parts = list(self.db_path.resolve().parts)
        lowered = [part.lower() for part in parts]
        if "local" in lowered and "db" in lowered:
            local_index = lowered.index("local")
            if len(parts) > local_index + 1:
                data_root = Path(*parts[:local_index])
                profile_name = parts[local_index + 1]
                return data_root / "backups" / profile_name
        if "kasalar" in lowered and "db" in lowered:
            kasalar_index = lowered.index("kasalar")
            if len(parts) > kasalar_index + 1:
                data_root = Path(*parts[:kasalar_index])
                profile_name = parts[kasalar_index + 1]
                return data_root / "backups" / profile_name
        return self.base_dir / "backups" / "manager"

    def _resolve_log_path(self) -> Path:
        parts = list(self.db_path.resolve().parts)
        lowered = [part.lower() for part in parts]
        if "local" in lowered and "db" in lowered:
            local_index = lowered.index("local")
            if len(parts) > local_index + 1:
                data_root = Path(*parts[:local_index])
                profile_name = parts[local_index + 1]
                return data_root / "logs" / profile_name / "backup_log.json"
        if "kasalar" in lowered and "db" in lowered:
            kasalar_index = lowered.index("kasalar")
            if len(parts) > kasalar_index + 1:
                data_root = Path(*parts[:kasalar_index])
                profile_name = parts[kasalar_index + 1]
                return data_root / "logs" / profile_name / "backup_log.json"
        return self.base_dir / "logs" / "backup_log.json"

    @measure("backup_suresi", lambda self, reason="startup": f"backup_if_needed reason={reason}")
    def backup_if_needed(self, reason: str = "startup") -> BackupResult | None:
        """Take a backup if the current daily file is missing or older than 10 minutes."""
        last = self.settings_db.get_setting("last_backup_at", "")
        now = datetime.now()
        if last:
            try:
                if now - datetime.fromisoformat(last) < self.BACKUP_INTERVAL:
                    return None
            except ValueError:
                pass
        return self.create_backup(reason=reason, now=now)

    @measure("backup_suresi", lambda self, reason="manual", now=None: f"create_backup reason={reason}")
    def create_backup(self, reason: str = "manual", now: datetime | None = None) -> BackupResult:
        now = now or datetime.now()
        day = business_day(now)
        month = business_month(day)
        local_dir = self.local_root / month
        local_dir.mkdir(parents=True, exist_ok=True)

        local_path = local_dir / f"sales_{day}.db"
        tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")

        try:
            self._sqlite_backup(self.db_path, tmp_path)
            if tmp_path.stat().st_size <= 0:
                raise BackupError("Yedek dosyasi bos olusturuldu.")
            os.replace(tmp_path, local_path)
            fsync_parent(local_path)
            checksum = self._write_checksum(local_path)

            drive_path = ""
            drive_error = ""
            status = "local_only"
            message = "Yerel yedek alindi."

            result = BackupResult(
                ok=True,
                status=status,
                message=message,
                local_path=str(local_path),
                drive_path=drive_path,
                checksum=checksum,
                error=drive_error,
            )
            self._record_result(result, reason)
            self._backup_list_cache = None
            return result
        except Exception as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            result = BackupResult(
                ok=False,
                status="failed",
                message=f"Yedek alinamadi: {exc}",
                error=f"{exc}\n{traceback.format_exc()}",
            )
            self._record_result(result, reason)
            self._backup_list_cache = None
            return result

    def set_drive_root(self, folder: str) -> None:
        self.settings_db.set_settings({"drive_backup_root": folder})

    def get_drive_root_setting(self) -> str:
        return self.settings_db.get_setting("drive_backup_root", "")

    def get_service_account_json(self) -> str:
        return ""

    def get_drive_folder_id(self) -> str:
        return ""

    def get_drive_root(self) -> Path | None:
        raw = self.get_drive_root_setting().strip()
        if not raw:
            return None
        root = Path(raw)
        if not root.exists() or not root.is_dir():
            return None
        return root

    def sync_missing_to_drive(self) -> BackupResult:
        return BackupResult(False, "disabled", "Google Drive yedekleme pasif. Yerel yedek sistemi kullanılıyor.")

    def restore_backup(self, backup_path: str) -> BackupResult:
        source = Path(backup_path)
        if not source.exists() or source.stat().st_size <= 0:
            raise BackupError("Secilen yedek dosyasi bulunamadi veya bos.")
        self._verify_sqlite(source)

        emergency = self._emergency_backup()
        tmp_restore = self.db_path.with_suffix(self.db_path.suffix + ".restore_tmp")
        shutil.copy2(source, tmp_restore)
        if tmp_restore.stat().st_size <= 0:
            tmp_restore.unlink(missing_ok=True)
            raise BackupError("Geri yukleme kopyasi bos olustu.")
        os.replace(tmp_restore, self.db_path)

        result = BackupResult(
            True,
            "restored",
            "Yedekten geri yukleme tamamlandi. Uygulamayi yeniden baslatmaniz onerilir.",
            local_path=str(source),
            drive_path="",
            checksum=self._sha256(source),
        )
        self.settings_db.set_settings({"last_restore_source": str(source), "last_restore_emergency": str(emergency)})
        self._record_result(result, "restore")
        return result

    @measure("gereksiz_dosya_taramasi", lambda self: "list_backups")
    def list_backups(self) -> list[dict[str, str]]:
        now_ts = datetime.now().timestamp()
        if self._backup_list_cache and now_ts - self._backup_list_cache[0] < 5:
            return list(self._backup_list_cache[1])
        items: list[dict[str, str]] = []
        for root in (self.local_root,):
            if not root.exists():
                continue
            for path in sorted(root.rglob("sales_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
                items.append(
                    {
                        "month": path.stem.replace("sales_", "")[:7],
                        "name": path.name,
                        "path": str(path),
                        "size": str(path.stat().st_size),
                        "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
        self._backup_list_cache = (now_ts, items)
        return list(items)

    def get_status(self) -> dict[str, str]:
        return {
            "last_local_backup": self.settings_db.get_setting("last_local_backup", ""),
            "last_drive_backup": self.settings_db.get_setting("last_drive_backup", ""),
            "last_backup_status": self.settings_db.get_setting("last_backup_status", ""),
            "last_backup_error": self.settings_db.get_setting("last_backup_error", ""),
            "last_backup_at": self.settings_db.get_setting("last_backup_at", ""),
            "drive_backup_root": self.get_drive_root_setting(),
        }

    def read_archive_summary(self, backup_path: str, limit: int = 200) -> dict[str, Any]:
        path = Path(backup_path)
        self._verify_sqlite(path)
        uri = f"file:{path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            data: dict[str, Any] = {"tables": sorted(tables), "path": str(path)}
            data["sales"] = self._safe_rows(conn, tables, "sales", "id", limit)
            data["customers"] = self._safe_rows(conn, tables, "customers", "id", limit)
            data["expenses"] = self._safe_rows(conn, tables, "expenses", "id", limit)
            data["transactions"] = self._safe_rows(conn, tables, "transactions", "id", limit)
            return data

    def _safe_rows(self, conn: sqlite3.Connection, tables: set[str], table: str, order_col: str, limit: int) -> list[dict[str, Any]]:
        if table not in tables:
            return []
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        order = order_col if order_col in columns else columns[0]
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def _sqlite_backup(self, source: Path, target: Path) -> None:
        if not source.exists():
            raise BackupError(f"Ana veritabani bulunamadi: {source}")
        sqlite_online_backup(source, target)

    def _verify_sqlite(self, path: Path) -> None:
        with closing(sqlite3.connect(str(path))) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError("Yedek veritabani butunluk kontrolunden gecemedi.")

    def _copy_to_drive(self, local_path: Path, drive_root: Path, month: str) -> str:
        dest_dir = drive_root / "backups" / month
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / local_path.name
        atomic_copy_file(local_path, dest)
        return str(dest)

    def _copy_checksum_to_drive(self, local_path: Path, drive_path: Path) -> None:
        checksum_path = local_path.with_suffix(".sha256")
        if checksum_path.exists():
            atomic_copy_file(checksum_path, drive_path.with_suffix(".sha256"))

    def _emergency_backup(self) -> Path:
        now = datetime.now()
        folder = self.emergency_root / now.strftime("%Y-%m")
        folder.mkdir(parents=True, exist_ok=True)
        target = self._unique_path(folder / f"emergency_before_restore_{now.strftime('%Y-%m-%d_%H-%M-%S')}.db")
        self._sqlite_backup(self.db_path, target)
        return target

    def _write_checksum(self, path: Path) -> str:
        checksum = self._sha256(path)
        from safe_io import atomic_write_text
        atomic_write_text(path.with_suffix(".sha256"), f"{checksum}  {path.name}\n", encoding="utf-8")
        return checksum

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _record_result(self, result: BackupResult, reason: str) -> None:
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "date": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "local_path": result.local_path,
            "drive_path": result.drive_path,
            "status": result.status,
            "checksum": result.checksum,
            "error": result.error,
        }
        log = []
        if self.log_path.exists():
            try:
                log = json.loads(self.log_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log = []
        log.append(entry)
        atomic_write_json(self.log_path, log[-1000:])

        payload = {
            "last_backup_status": result.status,
            "last_backup_error": result.error,
            "last_backup_checksum": result.checksum,
            "last_backup_at": entry["date"],
        }
        if result.local_path:
            payload["last_local_backup"] = result.local_path
        if result.drive_path:
            payload["last_drive_backup"] = result.drive_path
        self.settings_db.set_settings(payload)
