# -*- coding: utf-8 -*-
"""Admin password security for archive and restore operations."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time


class SecurityManager:
    """PBKDF2-HMAC-SHA256 password storage with short lockout protection."""

    HASH_KEY = "archive_admin_password_hash"
    SALT_KEY = "archive_admin_password_salt"
    ITER_KEY = "archive_admin_password_iterations"
    FAIL_KEY = "archive_admin_failed_attempts"
    LOCK_KEY = "archive_admin_lock_until"
    DEFAULT_ITERATIONS = 220_000

    def __init__(self, settings_db):
        self.settings_db = settings_db

    def has_password(self) -> bool:
        return bool(self.settings_db.get_setting(self.HASH_KEY, ""))

    def set_password(self, password: str) -> None:
        if len(password or "") < 4:
            raise ValueError("Admin sifresi en az 4 karakter olmali.")
        salt = secrets.token_hex(16)
        iterations = self.DEFAULT_ITERATIONS
        digest = self._hash(password, salt, iterations)
        self.settings_db.set_settings(
            {
                self.HASH_KEY: digest,
                self.SALT_KEY: salt,
                self.ITER_KEY: str(iterations),
                self.FAIL_KEY: "0",
                self.LOCK_KEY: "0",
            }
        )

    def verify_password(self, password: str) -> tuple[bool, str]:
        locked, message = self._lock_status()
        if locked:
            return False, message
        if not self.has_password():
            return False, "Admin arsiv sifresi henuz olusturulmamis."

        salt = self.settings_db.get_setting(self.SALT_KEY, "")
        iterations = int(self.settings_db.get_setting(self.ITER_KEY, str(self.DEFAULT_ITERATIONS)) or self.DEFAULT_ITERATIONS)
        stored = self.settings_db.get_setting(self.HASH_KEY, "")
        candidate = self._hash(password or "", salt, iterations)
        if hmac.compare_digest(stored, candidate):
            self.settings_db.set_settings({self.FAIL_KEY: "0", self.LOCK_KEY: "0"})
            return True, "Sifre dogru."

        failed = int(self.settings_db.get_setting(self.FAIL_KEY, "0") or 0) + 1
        payload = {self.FAIL_KEY: str(failed)}
        if failed >= 3:
            payload[self.LOCK_KEY] = str(int(time.time() + 30))
            payload[self.FAIL_KEY] = "0"
            message = "3 hatali deneme yapildi. 30 saniye sonra tekrar deneyin."
        else:
            message = "Admin sifresi hatali."
        self.settings_db.set_settings(payload)
        return False, message

    def _lock_status(self) -> tuple[bool, str]:
        lock_until = int(float(self.settings_db.get_setting(self.LOCK_KEY, "0") or 0))
        now = int(time.time())
        if lock_until > now:
            return True, f"Cok fazla hatali deneme. {lock_until - now} saniye sonra tekrar deneyin."
        return False, ""

    def _hash(self, password: str, salt: str, iterations: int) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            iterations,
        )
        return digest.hex()
