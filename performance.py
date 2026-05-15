# -*- coding: utf-8 -*-
"""Low-overhead performance diagnostics for MatadorsApp.

This module only measures and logs. It must never change business flow.
"""

from __future__ import annotations

import atexit
import functools
import os
import queue
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar


PERFORMANCE_DEBUG = True
_SLOW_MS = 250.0
_QUEUE: "queue.Queue[str | None]" = queue.Queue(maxsize=2000)
_THREAD_STARTED = False
_THREAD_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None

F = TypeVar("F", bound=Callable)


def _log_path() -> Path:
    try:
        from path_utils import get_logs_dir

        root = Path(get_logs_dir())
    except Exception:
        root = Path(__file__).resolve().parent / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root / "performance.log"


def _writer() -> None:
    path = _log_path()
    while True:
        line = _QUEUE.get()
        if line is None:
            return
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass


def _ensure_writer() -> None:
    global _THREAD_STARTED, _THREAD
    if _THREAD_STARTED:
        return
    with _THREAD_LOCK:
        if _THREAD_STARTED:
            return
        try:
            _THREAD = threading.Thread(target=_writer, name="MatadorsPerformanceLogger", daemon=True)
            _THREAD.start()
            _THREAD_STARTED = True
            atexit.register(shutdown_performance_logger)
        except Exception:
            pass


def shutdown_performance_logger() -> None:
    try:
        _QUEUE.put_nowait(None)
        if _THREAD is not None and _THREAD.is_alive():
            _THREAD.join(timeout=1.0)
    except Exception:
        pass


def log_performance(operation: str, elapsed_ms: float, detail: str = "") -> None:
    if not PERFORMANCE_DEBUG:
        return
    try:
        _ensure_writer()
        timestamp = datetime.now().isoformat(timespec="seconds")
        suffix = f" | {detail}" if detail else ""
        line = f"[{timestamp}] {operation} -> {elapsed_ms:.2f} ms{suffix}"
        _QUEUE.put_nowait(line)
    except Exception:
        pass


def log_event(operation: str, detail: str = "") -> None:
    log_performance(operation, 0.0, detail)


@contextmanager
def perf_timer(operation: str, detail: str = ""):
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000.0
        extra = detail
        if elapsed >= _SLOW_MS:
            extra = f"{extra} | slow" if extra else "slow"
        log_performance(operation, elapsed, extra)


def measure(operation: str | None = None, detail_fn: Callable[..., str] | None = None):
    def decorator(func: F) -> F:
        name = operation or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            detail = ""
            if detail_fn:
                try:
                    detail = detail_fn(*args, **kwargs)
                except Exception:
                    detail = ""
            with perf_timer(name, detail):
                return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def audit_python_sources(root: str | Path | None = None) -> None:
    """Best-effort code hygiene scan, run in background and log-only."""
    if not PERFORMANCE_DEBUG:
        return
    if os.environ.get("MATADORS_PERF_AUDIT", "").strip() not in {"1", "true", "TRUE", "yes"}:
        return

    def worker() -> None:
        scan_root = Path(root or Path(__file__).resolve().parent)
        ignored = {"build", "dist", "__pycache__", ".git", ".next", "node_modules", "deploy_ready"}
        with perf_timer("kod_temizligi_taramasi", f"root={scan_root}"):
            for path in scan_root.rglob("*.py"):
                try:
                    if any(part in ignored for part in path.parts):
                        continue
                    rel = path.relative_to(scan_root)
                    stat = path.stat()
                    if stat.st_size > 300_000:
                        log_event("buyuk_python_dosyasi", f"{rel} | {stat.st_size} bytes")
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if len(lines) > 2000:
                        log_event("kullanilmayan_buyuk_dosya_taramasi_adayi", f"{rel} | {len(lines)} lines")
                    imports: dict[str, int] = {}
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith("import ") or stripped.startswith("from "):
                            imports[stripped] = imports.get(stripped, 0) + 1
                    for statement, count in imports.items():
                        if count > 1:
                            log_event("duplicate_import", f"{rel} | {statement} | count={count}")
                except Exception as exc:
                    log_event("kod_temizligi_taramasi_hata", f"{path} | {exc}")

    try:
        threading.Thread(target=worker, name="MatadorsPerformanceAudit", daemon=True).start()
    except Exception:
        pass
