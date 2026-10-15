"""
Cloud Backend Server (Free-Tier Compatible / Zero-Dependency).
Runs using Python standard library http.server.
Handles:
- Ingestion of streamed and backlogged samples (idempotent)
- Real-time online window calculation (< 5s latency)
- Cloud export endpoint for 'pipeline export --from cloud'
- Cloud results store
"""

import json
import logging
import os
import sqlite3
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Ensure parent directory is in sys.path for direct script execution
pkg_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(pkg_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from .analyzer import process_window
except (ImportError, ValueError):
    from pipeline_pkg.analyzer import process_window

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cloud_server")

CLOUD_DB_PATH = os.environ.get("CLOUD_DB_PATH", "cloud_store.db")


class CloudDatabase:
    def __init__(self, db_path: str = CLOUD_DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self.lock, self.conn:
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = NORMAL;")
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cloud_samples (
                session_id TEXT NOT NULL,
                sensor INTEGER NOT NULL,
                idx INTEGER NOT NULL,
                v0 INTEGER,
                v1 INTEGER,
                v2 INTEGER,
                arrived_at REAL,
                PRIMARY KEY (session_id, sensor, idx)
            );
            """)
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cloud_losses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sensor INTEGER NOT NULL,
                from_index INTEGER NOT NULL,
                to_index INTEGER,
                reason TEXT NOT NULL
            );
            """)
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cloud_results (
                session_id TEXT NOT NULL,
                window INTEGER NOT NULL,
                mode TEXT NOT NULL,
                data_json TEXT NOT NULL,
                computed_at REAL,
                PRIMARY KEY (session_id, window, mode)
            );
            """)

    def insert_samples(self, session_id: str, samples_list: list):
        now = time.time()
        rows = []
        for s in samples_list:
            vals = s["values"]
            v0 = vals[0] if len(vals) > 0 else None
            v1 = vals[1] if len(vals) > 1 else None
            v2 = vals[2] if len(vals) > 2 else None
            rows.append((session_id, s["sensor"], s["index"], v0, v1, v2, now))

        with self.lock, self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO cloud_samples (session_id, sensor, idx, v0, v1, v2, arrived_at) VALUES (?, ?, ?, ?, ?, ?, ?);",
                rows
            )

    def insert_losses(self, session_id: str, losses_list: list):
        with self.lock, self.conn:
            for l in losses_list:
                self.conn.execute(
                    "INSERT INTO cloud_losses (session_id, sensor, from_index, to_index, reason) VALUES (?, ?, ?, ?, ?);",
                    (session_id, l["sensor"], l["from_index"], l.get("to_index"), l.get("reason", "unknown"))
                )

    def save_result(self, session_id: str, window: int, result_dict: dict):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO cloud_results (session_id, window, mode, data_json, computed_at) VALUES (?, ?, ?, ?, ?);",
                (session_id, window, "online", json.dumps(result_dict), time.time())
            )

    def get_max_sample_index(self, session_id: str) -> int:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT MAX(idx) FROM cloud_samples WHERE session_id = ?;", (session_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else -1

    def get_window_samples(self, session_id: str, start_idx: int, end_idx: int):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT sensor, idx, v0, v1, v2 FROM cloud_samples WHERE session_id = ? AND idx >= ? AND idx <= ?;",
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
                "SELECT sensor, idx, v0, v1, v2 FROM cloud_samples WHERE session_id = ? ORDER BY sensor, idx ASC;",
                (session_id,)
            )
            for s, idx, v0, v1, v2 in cur:
                vals = [v0, v1, v2] if s == 1 else [v0, v1]
                yield json.dumps({"sensor": s, "index": idx, "values": vals})

            cur.execute(
                "SELECT sensor, from_index, to_index, reason FROM cloud_losses WHERE session_id = ? ORDER BY id ASC;",
                (session_id,)
            )
            for s, f_idx, t_idx, reason in cur:
                yield json.dumps({"sensor": s, "from_index": f_idx, "to_index": t_idx, "reason": reason})

    def export_results(self, session_id: str):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT data_json FROM cloud_results WHERE session_id = ? ORDER BY window ASC;",
                (session_id,)
            )
            for (d_json,) in cur:
                yield d_json


class CloudHandler(BaseHTTPRequestHandler):
    db: CloudDatabase = None  # Injected

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}\n')
            return

        session_id = query.get("session_id", [None])[0]
        if path == "/api/export":
            if not session_id:
                self.send_response(400)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for line in self.db.export_data(session_id):
                self.wfile.write((line + "\n").encode("utf-8"))
            return

        if path == "/api/results":
            if not session_id:
                self.send_response(400)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for line in self.db.export_results(session_id):
                self.wfile.write((line + "\n").encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed_url = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)

        if parsed_url.path == "/api/ingest":
            try:
                payload = json.loads(body.decode("utf-8"))
                session_id = payload.get("session_id")
                samples = payload.get("samples", [])
                losses = payload.get("losses", [])

                if session_id:
                    if samples:
                        self.db.insert_samples(session_id, samples)
                    if losses:
                        self.db.insert_losses(session_id, losses)

                    # Trigger online window calculation for ready windows
                    max_idx = self.db.get_max_sample_index(session_id)
                    max_window = max_idx // 400
                    for w in range(max(0, max_window - 5), max_window):
                        # Calculate within 5 seconds requirement
                        start_i = 400 * w
                        end_i = start_i + 399
                        s1, s2 = self.db.get_window_samples(session_id, 400 * max(0, w - 4), end_i + 1)
                        res = process_window(w, s1, s2, mode="online")
                        self.db.save_result(session_id, w, res)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "accepted"}\n')
            except Exception as e:
                logger.error(f"Error handling ingest: {e}")
                self.send_response(500)
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()


def run_cloud_server(port: int = 8080, db_path: str = "cloud_store.db"):
    db = CloudDatabase(db_path)
    CloudHandler.db = db
    server = HTTPServer(("0.0.0.0", port), CloudHandler)
    logger.info(f"Cloud server running on port {port}...")
    server.serve_forever()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_cloud_server(port=port)
