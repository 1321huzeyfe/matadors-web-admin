# -*- coding: utf-8 -*-
import sqlite3
import locale

try:
    locale.setlocale(locale.LC_ALL, 'Turkish_Turkey.1254')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'tr_TR.UTF-8')
    except locale.Error:
        pass
except Exception as e:
    print(f"Database locale configuration warning: {e}")

except Exception as e:
    print(f"Database locale configuration warning: {e}")
    pass  # Continue with default locale


DEFAULT_PRODUCTS = [
    ("1L Su", "Su", 20.0, 120),
    ("1.5L Su", "Su", 25.0, 80),
    ("Soda", "İçecek", 18.0, 90),
    ("Americano", "Kahve", 45.0, 50),
    ("Filtre Kahve", "Kahve", 40.0, 50),
    ("Protein Bar", "Bar", 70.0, 60),
    ("Carnitine Shot", "Takviye", 85.0, 40),
    ("Pre-Workout", "Takviye", 110.0, 35),
    ("Bcaa", "Takviye", 95.0, 30),
    ("Whey Protein Tek Kullanımlık", "Takviye", 120.0, 25),
]


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection_pool = []
        self._max_connections = 5
        self._init_db()

    def _connect(self):
        """Create a database connection with optimized settings."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # Enable WAL mode for better concurrency
        conn.execute("PRAGMA synchronous = NORMAL")  # Balance between safety and speed
        conn.execute("PRAGMA cache_size = 10000")  # Increase cache size
        conn.execute("PRAGMA temp_store = MEMORY")  # Store temp tables in memory
        conn.row_factory = sqlite3.Row
        return conn

    def _get_connection(self):
        """Get a connection from the pool or create a new one."""
        if self._connection_pool:
            return self._connection_pool.pop()
        return self._connect()

    def _return_connection(self, conn):
        """Return a connection to the pool if not full."""
        if len(self._connection_pool) < self._max_connections:
            self._connection_pool.append(conn)
        else:
            conn.close()


