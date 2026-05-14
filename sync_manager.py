# -*- coding: utf-8 -*-
"""Non-blocking SQLite and report sync for Google Drive folder mirroring."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from profile_manager import PROFILE_KASA, PROFILE_MANAGER, Profile, ProfileManager
from cashier_data_store import CashierDataStore
from path_utils import (
    business_day,
    get_admin_cashier_summary_path,
    get_admin_dashboard_path,
    get_drive_daily_backup_path,
    get_drive_kasa_lock_path,
    get_drive_kasa_log_path,
    get_drive_kasa_customers_db_path,
    get_drive_kasa_reports_dir,
    get_drive_kasa_stock_db_path,
    get_drive_kasa_status_path,
    get_kasa_daily_backup_path,
)
from safe_io import atomic_copy_file, atomic_write_json, sqlite_online_backup


SYNC_INTERVAL_SECONDS = 5 * 60
SYNC_DEBOUNCE_SECONDS = 45
STALE_AFTER_SECONDS = 5 * 60
BACKUP_INTERVAL_SECONDS = 10 * 60
LOCK_STALE_SECONDS = 15 * 60


@dataclass
class SyncStatus:
    username: str
    ok: bool
    last_sync: str = ""
    message: str = ""
    delayed: bool = False
    state: str = "iyi"
    delay_minutes: int = 0


class SyncManager:
    def __init__(self, profile_manager: ProfileManager, db_factory: Callable[[str], object] | None = None, shared_data_manager=None):
        self.profile_manager = profile_manager
        self.db_factory = db_factory
        self.shared_data_manager = shared_data_manager
        self.cashier_data_store = CashierDataStore()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._debounce_timer: threading.Timer | None = None
        self._active_profile: Profile | None = None
        self._last_error = ""

    def start_for_profile(self, profile: Profile, interval_seconds: int = SYNC_INTERVAL_SECONDS) -> None:
        self.stop()
        self._active_profile = profile
        if profile.profile_type != PROFILE_KASA:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(profile, interval_seconds), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        if self._active_profile and self._active_profile.profile_type == PROFILE_KASA:
            try:
                self.sync_profile(self._active_profile)
            except Exception:
                pass
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def sync_now_async(self, callback: Callable[[SyncStatus], None] | None = None) -> None:
        profile = self._active_profile
        if not profile:
            return
        if self._debounce_timer:
            self._debounce_timer.cancel()

        def delayed_runner():
            self._debounce_timer = None
            self._run_async_sync(profile, callback)

        self._debounce_timer = threading.Timer(SYNC_DEBOUNCE_SECONDS, delayed_runner)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def sync_now_force_async(self, callback: Callable[[SyncStatus], None] | None = None) -> None:
        profile = self._active_profile
        if not profile:
            return
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        self._run_async_sync(profile, callback)

    def _run_async_sync(self, profile: Profile, callback: Callable[[SyncStatus], None] | None = None) -> None:
        def runner():
            result = self.sync_profile(profile)
            if callback:
                callback(result)

        threading.Thread(target=runner, daemon=True).start()

    def sync_profile(self, profile: Profile) -> SyncStatus:
        if profile.profile_type != PROFILE_KASA:
            return SyncStatus(profile.username, True, message="YÃ¶netici profili sadece okur.", state="iyi")
        with self._lock:
            lock_acquired = False
            try:
                self._assert_kasa_drive_scope(profile)
                self._acquire_lock(profile)
                lock_acquired = True
                profile.reports_dir.mkdir(parents=True, exist_ok=True)
                if profile.local_db_path.exists():
                    if self.shared_data_manager:
                        self.shared_data_manager.sync_products_to_local(str(profile.local_db_path))
                        self._append_pending_customers(profile)
                        self.shared_data_manager.merge_pending_customers(actor="sync_manager")
                    self._sqlite_backup(profile.local_db_path, profile.drive_db_path)
                    self._sqlite_backup(profile.local_db_path, profile.drive_dir / "customers.db")
                    self._sqlite_backup(profile.local_db_path, profile.drive_dir / "stock.db")
                    backup_path = get_kasa_daily_backup_path(profile.username, business_day())
                    self._sqlite_backup_if_due(profile.local_db_path, backup_path)
                    drive_backup_path = self.profile_manager.get_drive_root() / "backups" / business_day()[:7] / f"{profile.username}_sales_{business_day()}.db"
                    self._sqlite_backup_if_due(profile.local_db_path, drive_backup_path)
                    self.cashier_data_store.export_profile(profile)
                    self._write_standard_reports(profile)
                conflicts = self._conflicted_files(profile)
                warning = ""
                if conflicts:
                    warning = "Drive klasöründe conflicted/kopya dosya var: " + ", ".join(conflicts[:5])
                status = self._write_metadata(profile, True, warning, forced_state="uyarı" if warning else None)
                if warning:
                    status.message = warning
                    status.delayed = True
                self._log(profile, "Senkron tamamlandÄ±.")
                return status
            except Exception as exc:
                self._last_error = str(exc)
                self._log(profile, f"Senkron yapÄ±lamadÄ±: {exc}")
                try:
                    return self._write_metadata(profile, False, str(exc))
                except Exception:
                    return SyncStatus(profile.username, False, message=f"Senkron yapÄ±lamadÄ±: {exc}", delayed=True, state="uyarÄ±")
            finally:
                if lock_acquired:
                    self._release_lock(profile)

    def copy_report_to_drive(self, report_path: str | Path, profile: Profile | None = None, report_type: str = "reports") -> str:
        profile = profile or self._active_profile
        if not profile or not Path(report_path).exists():
            return ""
        if profile.profile_type != PROFILE_KASA:
            return ""
        dest_root = profile.drive_dir / "reports"
        source = Path(report_path)
        try:
            if profile.profile_type == PROFILE_KASA and source.resolve().is_relative_to(profile.kasa_reports_dir.resolve()):
                return str(source)
        except (OSError, ValueError):
            pass
        month_dir = dest_root / datetime.now().strftime("%Y-%m") / report_type
        month_dir.mkdir(parents=True, exist_ok=True)
        dest = month_dir / source.name
        atomic_copy_file(source, dest)
        return str(dest)

    def manager_statuses(self, cashiers: list[dict]) -> list[SyncStatus]:
        statuses: list[SyncStatus] = []
        now = datetime.now()
        for user in cashiers:
            profile = self.profile_manager.ensure_cashier_profile(user["username"])
            meta = self._read_metadata(profile)
            last_sync = meta.get("son_senkron") or meta.get("last_sync", "")
            delay_minutes = self._delay_minutes(last_sync, now)
            state = self._state_for_delay(delay_minutes)
            message = meta.get("hata") or meta.get("error", "")
            if meta.get("conflicted_files"):
                message = "Drive conflicted/kopya uyarısı: " + ", ".join(meta.get("conflicted_files", [])[:5])
                if state == "iyi":
                    state = "uyarı"
            statuses.append(
                SyncStatus(
                    username=user["username"],
                    ok=meta.get("durum", state) != "gecikmiÅŸ" and bool(meta.get("ok", profile.drive_db_path.exists())),
                    last_sync=last_sync,
                    message=message,
                    delayed=delay_minutes > 5,
                    state=state,
                    delay_minutes=delay_minutes,
                )
            )
        return statuses

    def _loop(self, profile: Profile, interval_seconds: int) -> None:
        self.sync_profile(profile)
        while not self._stop.wait(interval_seconds):
            self.sync_profile(profile)

    def _append_pending_customers(self, profile: Profile) -> None:
        if not self.shared_data_manager:
            return
        with closing(sqlite3.connect(str(profile.local_db_path))) as conn, conn:
            conn.row_factory = sqlite3.Row
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(customers)").fetchall()}
            if "customer_uuid" not in cols:
                return
            if "pending_sync" not in cols:
                conn.execute("ALTER TABLE customers ADD COLUMN pending_sync INTEGER DEFAULT 1")
            rows = conn.execute(
                """
                SELECT * FROM customers
                WHERE COALESCE(pending_sync, 1) = 1
                ORDER BY id
                """
            ).fetchall()
            for row in rows:
                payload = dict(row)
                if not payload.get("customer_uuid"):
                    payload["customer_uuid"] = f"{profile.username}-{payload['id']}"
                    conn.execute("UPDATE customers SET customer_uuid = ? WHERE id = ?", (payload["customer_uuid"], payload["id"]))
                self.shared_data_manager.append_pending_customer(profile.username, payload)
                conn.execute("UPDATE customers SET pending_sync = 0 WHERE id = ?", (row["id"],))

    def _sqlite_backup(self, source: Path, target: Path) -> None:
        if not source.exists():
            return
        self._assert_safe_copy_target(source, target)
        sqlite_online_backup(source, target)

    def _sqlite_backup_if_due(self, source: Path, target: Path) -> None:
        if target.exists():
            age = datetime.now() - datetime.fromtimestamp(target.stat().st_mtime)
            if age.total_seconds() < BACKUP_INTERVAL_SECONDS:
                return
        self._sqlite_backup(source, target)

    def _write_standard_reports(self, profile: Profile) -> None:
        """Standard sync does not create report files; report actions create PDF files."""
        return None

    def _write_admin_panel_cashier(self, profile: Profile, status: SyncStatus) -> None:
        if profile.profile_type != PROFILE_KASA or not profile.local_db_path.exists():
            return
        payload = self._cashier_admin_summary(profile, status)
        path = get_admin_cashier_summary_path(profile.username, drive_root=self.profile_manager.get_drive_root())
        self._write_json_atomic(path, payload)

    def _write_admin_dashboard(self) -> None:
        cashiers_dir = get_admin_cashier_summary_path("_probe_", drive_root=self.profile_manager.get_drive_root()).parent
        rows: list[dict] = []
        if cashiers_dir.exists():
            for path in sorted(cashiers_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(data, dict):
                    rows.append(data)
        dashboard = {
            "toplam_satis": sum(float(row.get("bugunku_satis", 0) or 0) for row in rows),
            "toplam_islem": sum(int(row.get("bugunku_islem", 0) or 0) for row in rows),
            "aktif_kasa": sum(1 for row in rows if row.get("durum") in ("iyi", "uyarÄ±")),
            "gecikmis_kasa": sum(1 for row in rows if row.get("durum") == "gecikmiÅŸ"),
            "toplam_borc": sum(float(row.get("toplam_borc", 0) or 0) for row in rows),
            "son_guncelleme": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_json_atomic(get_admin_dashboard_path(drive_root=self.profile_manager.get_drive_root()), dashboard)

    def _cashier_admin_summary(self, profile: Profile, status: SyncStatus) -> dict:
        today = business_day()
        empty = {
            "bugunku_satis": 0.0,
            "bugunku_islem": 0,
            "aktif_musteri": 0,
            "toplam_borc": 0.0,
            "kritik_stok_sayisi": 0,
            "son_islem_saati": "",
        }
        with closing(sqlite3.connect(str(profile.local_db_path))) as conn:
            conn.row_factory = sqlite3.Row
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "sales" in tables:
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(total), 0) AS total, COUNT(*) AS count_value, MAX(created_at) AS last_time
                    FROM sales
                    WHERE date(created_at) = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1
                    """,
                    (today,),
                ).fetchone()
                empty["bugunku_satis"] = float(row["total"] or 0)
                empty["bugunku_islem"] += int(row["count_value"] or 0)
                empty["son_islem_saati"] = row["last_time"] or ""
            if "transactions" in tables:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS count_value, MAX(created_at) AS last_time
                    FROM transactions
                    WHERE date(created_at) = ? AND COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1
                    """,
                    (today,),
                ).fetchone()
                empty["bugunku_islem"] += int(row["count_value"] or 0)
                if row["last_time"] and (not empty["son_islem_saati"] or row["last_time"] > empty["son_islem_saati"]):
                    empty["son_islem_saati"] = row["last_time"]
            if "customers" in tables:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS active_count,
                           COALESCE(SUM(CASE WHEN balance < 0 THEN -balance ELSE 0 END), 0) AS debt_total
                    FROM customers
                    WHERE COALESCE(archived, 0) = 0 AND COALESCE(is_active, 1) = 1
                    """
                ).fetchone()
                empty["aktif_musteri"] = int(row["active_count"] or 0)
                empty["toplam_borc"] = float(row["debt_total"] or 0)
            if "products" in tables:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS critical_count
                    FROM products
                    WHERE COALESCE(archived, 0) = 0
                      AND COALESCE(is_active, 1) = 1
                      AND COALESCE(active, 1) = 1
                      AND COALESCE(stock, 0) <= 5
                    """
                ).fetchone()
                empty["kritik_stok_sayisi"] = int(row["critical_count"] or 0)
        return {
            "kasa_adi": profile.username,
            "son_senkron": status.last_sync,
            "durum": status.state,
            **empty,
        }

    def _write_json_atomic(self, path: Path, payload: dict) -> None:
        atomic_write_json(path, payload)

    def _metadata_path(self, profile: Profile) -> Path:
        return profile.drive_dir / "sync_status.json"

    def _write_metadata(self, profile: Profile, ok: bool, error: str, forced_state: str | None = None) -> SyncStatus:
        now = datetime.now()
        last_sync = now.isoformat(timespec="seconds")
        delay_minutes = 0 if ok else self._delay_minutes(last_sync, now)
        state = self._state_for_delay(delay_minutes)
        if not ok:
            state = "uyarÄ±"
        if forced_state:
            state = forced_state
        conflicted = self._conflicted_files(profile)
        payload = {
            "kasa_adi": profile.username,
            "son_senkron": last_sync,
            "durum": state,
            "gecikme_dk": delay_minutes,
            "hata": error,
            "conflicted_files": conflicted,
            "username": profile.username,
            "ok": ok,
            "last_sync": last_sync,
            "error": error,
        }
        path = self._metadata_path(profile)
        atomic_write_json(path, payload)
        return SyncStatus(profile.username, ok, last_sync, "Senkron tamamlandÄ±." if ok else f"Senkron yapÄ±lamadÄ±: {error}", delay_minutes > 5, state, delay_minutes)

    def _conflicted_files(self, profile: Profile) -> list[str]:
        if not profile.drive_dir.exists():
            return []
        needles = ("conflict", "conflicted", "kopya", "copy")
        out: list[str] = []
        for path in profile.drive_dir.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.casefold()
            if any(part in name for part in needles):
                out.append(str(path.relative_to(profile.drive_dir)))
        return sorted(out)

    def _read_metadata(self, profile: Profile) -> dict:
        path = self._metadata_path(profile)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _acquire_lock(self, profile: Profile) -> None:
        lock_path = profile.drive_dir / ".sync.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        if lock_path.exists():
            try:
                payload = json.loads(lock_path.read_text(encoding="utf-8"))
                created = datetime.fromisoformat(payload.get("zaman", ""))
                if (now - created).total_seconds() <= LOCK_STALE_SECONDS:
                    raise RuntimeError("Senkron ÅŸu anda baÅŸka bir iÅŸlem tarafÄ±ndan kullanÄ±lÄ±yor.")
            except json.JSONDecodeError:
                pass
            except ValueError:
                pass
            lock_path.unlink(missing_ok=True)
        payload = {"kasa_adi": profile.username, "bilgisayar": socket.gethostname(), "zaman": now.isoformat(timespec="seconds")}
        atomic_write_json(lock_path, payload)

    def _release_lock(self, profile: Profile) -> None:
        lock_path = profile.drive_dir / ".sync.lock"
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _assert_kasa_drive_scope(self, profile: Profile) -> None:
        if profile.profile_type != PROFILE_KASA:
            raise RuntimeError("YÃ¶netici profili Drive senkrona yazamaz.")
        drive_dir = profile.drive_dir.resolve()
        expected_name = profile.username
        if drive_dir.name != expected_name:
            raise RuntimeError("Kasa Drive klasÃ¶rÃ¼ profil adÄ±yla eÅŸleÅŸmiyor.")
        drive_dir.mkdir(parents=True, exist_ok=True)

    def _assert_safe_copy_target(self, source: Path, target: Path) -> None:
        src = source.resolve()
        dst = target.resolve()
        if src == dst:
            raise RuntimeError("Kaynak ve hedef aynÄ± dosya olamaz.")
        lower_parts = [part.lower() for part in dst.parts]
        if "drive_sync" in lower_parts:
            sync_index = lower_parts.index("drive_sync")
            if len(dst.parts) <= sync_index + 1:
                raise RuntimeError("Drive hedef kasa klasÃ¶rÃ¼ eksik.")

    def _delay_minutes(self, last_sync: str, now: datetime | None = None) -> int:
        if not last_sync:
            return 9999
        now = now or datetime.now()
        try:
            return max(0, int((now - datetime.fromisoformat(last_sync)).total_seconds() // 60))
        except ValueError:
            return 9999

    def _state_for_delay(self, delay_minutes: int) -> str:
        if delay_minutes <= 5:
            return "iyi"
        if delay_minutes <= 15:
            return "uyarÄ±"
        return "gecikmiÅŸ"

    def _log(self, profile: Profile, message: str) -> None:
        try:
            path = profile.kasa_logs_dir / "drive_sync.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat(timespec='seconds')} | {message}\n")
        except OSError:
            pass
