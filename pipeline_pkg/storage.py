"""
Crash-Safe Storage Engine using SQLite in WAL mode.
Provides zero-loss guarantees, bounded 0.25s power-cut flush intervals,
honest gap / loss tracking, and thread safety.
"""

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Tuple, Any

DEFAULT_DB_PATH = os.environ.get("PIPELINE_DB_PATH", "/var/lib/pipeline/pipeline.db")
if not os.path.exists(os.path.dirname(DEFAULT_DB_PATH)) and not os.environ.get("PIPELINE_DB_PATH"):
    DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".pipeline", "pipeline.db")


class StorageEngine:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.lock, self.conn:
            # WAL mode for crash safety & concurrent access
            self.conn.execute("PRAGMA journal_mode = WAL;")
            # FULL synchronous ensures OS page cache is synced on commit (fsync)
            self.conn.execute("PRAGMA synchronous = FULL;")
            self.conn.execute("PRAGMA busy_timeout = 30000;")

            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at REAL,
                ended_at REAL
            );
            """)

            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                session_id TEXT NOT NULL,
                sensor INTEGER NOT NULL,
                idx INTEGER NOT NULL,
                v0 INTEGER,
                v1 INTEGER,
                v2 INTEGER,
                synced INTEGER DEFAULT 0,
                PRIMARY KEY (session_id, sensor, idx)
            );
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_sync ON samples(session_id, synced, sensor, idx);")

            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS losses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sensor INTEGER NOT NULL,
                from_index INTEGER NOT NULL,
                to_index INTEGER,
                reason TEXT NOT NULL
            );
            """)

            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                session_id TEXT NOT NULL,
                window INTEGER NOT NULL,
                mode TEXT NOT NULL,
                data_json TEXT NOT NULL,
                synced INTEGER DEFAULT 0,
                PRIMARY KEY (session_id, window, mode)
            );
            """)

            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                val TEXT
            );
            """)

    def set_meta(self, key: str, val: str):
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta (key, val) VALUES (?, ?);", (key, val))

    def get_meta(self, key: str) -> Optional[str]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT val FROM meta WHERE key = ?;", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def start_session_if_new(self, session_id: str):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?);",
                (session_id, time.time())
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, val) VALUES (?, ?);",
                ("current_session_id", session_id)
            )

    def record_samples(self, session_id: str, sensor: int, first_index: int, values_list: List[List[int]]):
        """
        Atomically insert samples. Ignores duplicates if mock retransmits.
        """
        rows = []
        for offset, val in enumerate(values_list):
            idx = first_index + offset
            v0 = val[0] if len(val) > 0 else None
            v1 = val[1] if len(val) > 1 else None
            v2 = val[2] if len(val) > 2 else None
            rows.append((session_id, sensor, idx, v0, v1, v2))

        with self.lock, self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO samples (session_id, sensor, idx, v0, v1, v2) VALUES (?, ?, ?, ?, ?, ?);",
                rows
            )

    def record_loss(self, session_id: str, sensor: int, from_index: int, to_index: Optional[int], reason: str):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO losses (session_id, sensor, from_index, to_index, reason) VALUES (?, ?, ?, ?, ?);",
                (session_id, sensor, from_index, to_index, reason)
            )

    def save_result(self, session_id: str, window: int, mode: str, result_dict: Dict[str, Any]):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO results (session_id, window, mode, data_json) VALUES (?, ?, ?, ?);",
                (session_id, window, mode, json.dumps(result_dict))
            )

    def get_highest_index(self, session_id: str, sensor: int) -> Optional[int]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT MAX(idx) FROM samples WHERE session_id = ? AND sensor = ?;", (session_id, sensor))
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else None

    def get_status_counts(self, session_id: Optional[str] = None) -> Tuple[int, int, int]:
        with self.lock:
            cur = self.conn.cursor()
            if session_id:
                cur.execute("SELECT COUNT(*), SUM(synced) FROM samples WHERE session_id = ?;", (session_id,))
            else:
                cur.execute("SELECT COUNT(*), SUM(synced) FROM samples;")
            row = cur.fetchone()
            saved = row[0] if row and row[0] is not None else 0
            in_cloud = row[1] if row and row[1] is not None else 0
            backlog = saved - in_cloud
            return saved, in_cloud, backlog

    def get_unmerged_backlog(self, session_id: str, limit: int = 400) -> List[Tuple[int, int, List[int]]]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT sensor, idx, v0, v1, v2 FROM samples 
                   WHERE session_id = ? AND synced = 0 
                   ORDER BY idx ASC LIMIT ?;""",
                (session_id, limit)
            )
            res = []
            for s, idx, v0, v1, v2 in cur.fetchall():
                vals = [v0, v1] if v2 is None else [v0, v1, v2]
                res.append((s, idx, vals))
            return res

    def mark_synced(self, session_id: str, sensor: int, min_idx: int, max_idx: int):
        with self.lock, self.conn:
            self.conn.execute(
                """UPDATE samples SET synced = 1 
                   WHERE session_id = ? AND sensor = ? AND idx >= ? AND idx <= ?;""",
                (session_id, sensor, min_idx, max_idx)
            )

    def fetch_window_samples(self, session_id: str, start_idx: int, end_idx: int) -> Tuple[Dict[int, List[int]], Dict[int, List[int]]]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT sensor, idx, v0, v1, v2 FROM samples 
                   WHERE session_id = ? AND idx >= ? AND idx <= ?;""",
                (session_id, start_idx, end_idx)
            )
            s1, s2 = {}, {}
            for s, idx, v0, v1, v2 in cur.fetchall():
                if s == 1:
                    s1[idx] = [v0, v1, v2]
                elif s == 2:
                    s2[idx] = [v0, v1]
            return s1, s2

    def export_data(self, session_id: str):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT sensor, idx, v0, v1, v2 FROM samples WHERE session_id = ? ORDER BY sensor, idx ASC;",
                (session_id,)
            )
            for s, idx, v0, v1, v2 in cur:
                vals = [v0, v1, v2] if s == 1 else [v0, v1]
                yield json.dumps({"sensor": s, "index": idx, "values": vals})

            cur.execute(
                "SELECT sensor, from_index, to_index, reason FROM losses WHERE session_id = ? ORDER BY id ASC;",
                (session_id,)
            )
            for s, f_idx, t_idx, reason in cur:
                yield json.dumps({"sensor": s, "from_index": f_idx, "to_index": t_idx, "reason": reason})

    def export_results(self, session_id: str):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT data_json FROM results WHERE session_id = ? ORDER BY window ASC;",
                (session_id,)
            )
            for (d_json,) in cur:
                yield d_json

    def close(self):
        with self.lock:
            self.conn.close()
