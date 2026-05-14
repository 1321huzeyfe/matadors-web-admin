# -*- coding: utf-8 -*-
"""Small crash-safe file helpers used by Drive and local mirrors."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def fsync_parent(path: Path) -> None:
    """Best-effort parent directory fsync after atomic replace."""
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    fsync_parent(path)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def atomic_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp")
    with source.open("rb") as src, tmp.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    if tmp.stat().st_size != source.stat().st_size:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Kopyalanan dosya boyutu kaynak dosya ile eşleşmedi.")
    os.replace(tmp, target)
    fsync_parent(target)


def sqlite_online_backup(source: Path, target: Path) -> None:
    """Copy a SQLite database through SQLite's backup API, then atomically publish it."""
    if not source.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(str(source), timeout=30.0)) as src, closing(sqlite3.connect(str(tmp), timeout=30.0)) as dst:
        src.execute("PRAGMA busy_timeout = 30000")
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError("SQLite bütünlük kontrolü başarısız.")
    with tmp.open("r+b") as handle:
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    fsync_parent(target)
