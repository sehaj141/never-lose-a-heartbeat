"""
Ingestion Engine for biosignal-mock.
Manages TCP connection, zlib CRC-32 validation, honest gap logging,
session restart tracking, and retry protocol.
"""

import json
import logging
import socket
import time
import zlib
from typing import Optional, Tuple, Dict, Any

pkg_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(pkg_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from .storage import StorageEngine
except (ImportError, ValueError):
    from pipeline_pkg.storage import StorageEngine

logger = logging.getLogger("pipeline.collector")


def extract_data_slice_and_crc(raw_line: bytes) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    """
    Parses the JSON line, locates the raw byte substring of 'data' from '[' to matching ']',
    computes zlib CRC-32, and returns (computed_crc_hex, expected_crc_hex, parsed_json).
    """
    try:
        text = raw_line.decode("utf-8").strip()
        if not text:
            return None, None, None
        parsed = json.loads(text)
    except Exception as e:
        logger.warning(f"Malformed JSON from mock: {e}")
        return None, None, None

    expected_crc = parsed.get("crc32")
    
    # Locate "data": [ ... ] substring within raw bytes to verify exact bytes sent
    data_marker = b'"data":'
    idx = raw_line.find(data_marker)
    if idx == -1:
        data_marker = b'"data" :'
        idx = raw_line.find(data_marker)

    if idx == -1:
        return None, expected_crc, parsed

    # Find the first '[' after "data":
    start_bracket = raw_line.find(b'[', idx)
    if start_bracket == -1:
        return None, expected_crc, parsed

    # Find matching ']'
    bracket_count = 0
    end_bracket = -1
    for i in range(start_bracket, len(raw_line)):
        b = raw_line[i]
        if b == ord('['):
            bracket_count += 1
        elif b == ord(']'):
            bracket_count -= 1
            if bracket_count == 0:
                end_bracket = i
                break

    if end_bracket == -1:
        return None, expected_crc, parsed

    data_bytes = raw_line[start_bracket : end_bracket + 1]
    computed_crc = f"{zlib.crc32(data_bytes) & 0xffffffff:08x}"

    return computed_crc, str(expected_crc).lower() if expected_crc else None, parsed


class MockCollector:
    def __init__(self, storage: StorageEngine, host: str = "127.0.0.1", port: int = 7100):
        self.storage = storage
        self.host = host
        self.port = port
        self.running = False
        self.sock: Optional[socket.socket] = None
        self.buffer = bytearray()
        
        # State tracking per sensor
        self.current_session_id: Optional[str] = None
        self.expected_index: Dict[int, int] = {1: 0, 2: 0}
        self.last_flush_time = time.time()
        self.pending_samples_count = 0

    def connect(self) -> bool:
        """Connect or reconnect to the mock TCP server."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((self.host, self.port))
            self.sock = s
            self.buffer.clear()
            logger.info(f"Connected to mock server at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.debug(f"Failed to connect to mock server {self.host}:{self.port}: {e}")
            self.sock = None
            return False

    def _send_cmd(self, cmd_dict: dict):
        line = json.dumps(cmd_dict) + "\n"
        self.sock.sendall(line.encode("utf-8"))

    def _read_reply_line(self) -> Optional[bytes]:
        """Reads until newline is found."""
        while True:
            nl_idx = self.buffer.find(b"\n")
            if nl_idx != -1:
                line = bytes(self.buffer[:nl_idx])
                del self.buffer[: nl_idx + 1]
                return line
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return None
                self.buffer.extend(chunk)
            except socket.timeout:
                return None
            except Exception as e:
                logger.warning(f"Socket error while reading: {e}")
                return None

    def poll_sensor(self, sensor: int) -> bool:
        """
        Polls a single sensor once. Handles CRC checking, re-reading on corruption,
        session shifts, gap detection, and storage.
        """
        if not self.sock:
            if not self.connect():
                return False

        req_idx = self.expected_index[sensor]
        # Request data
        try:
            self._send_cmd({"cmd": "read", "sensor": sensor})
            raw_line = self._read_reply_line()
        except Exception as e:
            logger.warning(f"Error during socket communication: {e}")
            self.connect()
            return False

        if not raw_line:
            return False

        computed_crc, expected_crc, parsed = extract_data_slice_and_crc(raw_line)
        if not parsed:
            return False

        # Fault Check: Corrupt reply (wrong CRC32)
        if computed_crc != expected_crc:
            logger.warning(f"CRC mismatch for sensor {sensor}! (calc {computed_crc} != exp {expected_crc}). Requesting re-read.")
            try:
                # Re-read command specified in Section 6.2
                self._send_cmd({"cmd": "read", "sensor": sensor, "from_index": req_idx})
                raw_line = self._read_reply_line()
                if not raw_line:
                    return False
                computed_crc, expected_crc, parsed = extract_data_slice_and_crc(raw_line)
                if computed_crc != expected_crc or not parsed:
                    logger.error(f"Re-read also returned corrupt CRC for sensor {sensor}. Discarding.")
                    return False
            except Exception as e:
                logger.error(f"Failed to re-read corrupt packet: {e}")
                return False

        session_id = parsed.get("session_id")
        first_idx = parsed.get("first_index", 0)
        count = parsed.get("count", 0)
        data = parsed.get("data", [])
        lost_ranges = parsed.get("lost", [])

        # Session restart check
        if self.current_session_id is not None and session_id != self.current_session_id:
            logger.info(f"Session changed from {self.current_session_id} to {session_id}. Finalizing old session.")
            for s in [1, 2]:
                highest = self.storage.get_highest_index(self.current_session_id, s)
                loss_start = (highest + 1) if highest is not None else 0
                self.storage.record_loss(
                    self.current_session_id,
                    s,
                    from_index=loss_start,
                    to_index=None,
                    reason="mock_restarted_session_terminated"
                )
            self.expected_index = {1: 0, 2: 0}

        self.current_session_id = session_id
        self.storage.start_session_if_new(session_id)

        # Record explicit lost ranges reported by the mock
        for item in lost_ranges:
            f_idx = item.get("from_index")
            t_idx = item.get("to_index")
            reason = item.get("reason", "unknown")
            self.storage.record_loss(session_id, sensor, f_idx, t_idx, reason)
            # Advance expected index past lost range if needed
            if t_idx is not None and t_idx >= self.expected_index[sensor]:
                self.expected_index[sensor] = t_idx + 1

        # Check for unnotified gaps
        if first_idx > self.expected_index[sensor]:
            gap_start = self.expected_index[sensor]
            gap_end = first_idx - 1
            logger.warning(f"Detected unflagged gap on sensor {sensor}: [{gap_start}, {gap_end}]")
            self.storage.record_loss(session_id, sensor, gap_start, gap_end, "stream_gap_unflagged")
            self.expected_index[sensor] = first_idx

        # If duplicate packet received, first_idx + count <= expected_index
        # We record into storage; storage uses INSERT OR IGNORE so duplicates are deduplicated
        if count > 0 and data:
            self.storage.record_samples(session_id, sensor, first_idx, data)
            self.expected_index[sensor] = max(self.expected_index[sensor], first_idx + count)
            self.pending_samples_count += count

        return True

    def run_once(self):
        """Polls both Sensor 1 and Sensor 2."""
        self.poll_sensor(1)
        self.poll_sensor(2)

        # Enforce 250ms or 100-sample flush boundary (Criteria 3)
        now = time.time()
        if self.pending_samples_count >= 100 or (now - self.last_flush_time) >= 0.25:
            # SQLite in FULL synchronous commits and fsyncs on each transaction block
            self.last_flush_time = now
            self.pending_samples_count = 0
