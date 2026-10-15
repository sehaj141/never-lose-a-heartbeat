"""
Synchronization Manager and Network Watchdog.
Controls automatic switching between online and offline modes within <= 6 seconds.
Streams live data in online mode, processes locally in offline mode,
and replays backlogs upon network restoration.
"""

import json
import logging
import threading
import time
import urllib.request
import urllib.error
from typing import Optional

pkg_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(pkg_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from .storage import StorageEngine
    from .analyzer import process_window
except (ImportError, ValueError):
    from pipeline_pkg.storage import StorageEngine
    from pipeline_pkg.analyzer import process_window

logger = logging.getLogger("pipeline.sync")


class SyncManager:
    def __init__(self, storage: StorageEngine, cloud_url: str = "http://127.0.0.1:8080"):
        self.storage = storage
        self.cloud_url = cloud_url.rstrip("/")
        self.mode = "offline"  # Start safe; health probe transitions to online
        self.running = False
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.lock = threading.Lock()
        self.processed_offline_windows = set()

    def check_cloud_health(self) -> bool:
        """Probes the cloud health endpoint."""
        url = f"{self.cloud_url}/health"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.8) as resp:
                return resp.status == 200
        except Exception:
            return False

    def update_network_state(self):
        """
        Polls health and transitions state within <= 6s (Criterion 5: < 10s).
        """
        healthy = self.check_cloud_health()
        with self.lock:
            if healthy:
                self.consecutive_successes += 1
                self.consecutive_failures = 0
                if self.mode == "offline" and self.consecutive_successes >= 2:
                    logger.info("Network restored! Switching to ONLINE mode.")
                    self.mode = "online"
                    self.storage.set_meta("current_mode", "online")
            else:
                self.consecutive_failures += 1
                self.consecutive_successes = 0
                if self.mode == "online" and self.consecutive_failures >= 3:
                    logger.warning("Network connection lost! Switching to OFFLINE mode.")
                    self.mode = "offline"
                    self.storage.set_meta("current_mode", "offline")

    def sync_backlog_step(self, session_id: str, batch_size: int = 400) -> int:
        """
        Pushes a batch of unsynced samples to the cloud.
        Returns number of samples synced in this step.
        """
        backlog_samples = self.storage.get_unmerged_backlog(session_id, limit=batch_size)
        if not backlog_samples:
            return 0

        payload = {
            "session_id": session_id,
            "samples": [
                {"sensor": s, "index": idx, "values": vals}
                for s, idx, vals in backlog_samples
            ],
            "losses": []
        }

        url = f"{self.cloud_url}/api/ingest"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    # Group by sensor and update synced status
                    by_sensor = {}
                    for s, idx, _ in backlog_samples:
                        if s not in by_sensor:
                            by_sensor[s] = []
                        by_sensor[s].append(idx)
                    for s, indices in by_sensor.items():
                        self.storage.mark_synced(session_id, s, min(indices), max(indices))
                    return len(backlog_samples)
        except Exception as e:
            logger.debug(f"Sync step error: {e}")
        return 0

    def run_local_offline_processing(self, session_id: str):
        """
        When offline, compute Section 3 outputs on-device and record to local DB.
        """
        s1_max = self.storage.get_highest_index(session_id, 1) or 0
        s2_max = self.storage.get_highest_index(session_id, 2) or 0
        max_idx = min(s1_max, s2_max)
        latest_window = max_idx // 400

        for w in range(latest_window):
            if w not in self.processed_offline_windows:
                start_i = 400 * w
                end_i = start_i + 399
                # Include lookback for peaks (up to 4 windows back)
                lookback_start = 400 * max(0, w - 4)
                s1_map, s2_map = self.storage.fetch_window_samples(session_id, lookback_start, end_i + 1)
                
                result = process_window(w, s1_map, s2_map, mode="offline")
                self.storage.save_result(session_id, w, "offline", result)
                self.processed_offline_windows.add(w)

    def sync_loop(self):
        """Background synchronization & watchdog loop."""
        self.running = True
        while self.running:
            self.update_network_state()
            session_id = self.storage.get_meta("current_session_id")

            if session_id:
                if self.mode == "online":
                    # Catch-up or live streaming: keep flushing backlog
                    synced = self.sync_backlog_step(session_id, batch_size=800)
                    if synced == 0:
                        time.sleep(0.5)
                else:
                    # Offline mode: execute local Section 3 computations
                    self.run_local_offline_processing(session_id)
                    time.sleep(1.0)
            else:
                time.sleep(1.0)

    def stop(self):
        self.running = False
