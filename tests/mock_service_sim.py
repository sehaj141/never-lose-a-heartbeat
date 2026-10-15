"""
Mock Service Simulator (Python implementation mirroring biosignal-mock).
Allows rigorous end-to-end testing, fault injection, and verification
against Section 6 specification.
"""

import json
import socket
import sys
import threading
import time
import zlib
from typing import Dict, List, Optional


class MockSensorServer:
    def __init__(self, port: int = 7100, mode: str = "ramp", seed: int = 7):
        self.port = port
        self.mode = mode
        self.seed = seed
        self.session_id = "test_sess_01"
        self.running = False
        self.server_sock: Optional[socket.socket] = None
        
        # Buffer: keeps last 10 seconds (4000 samples)
        self.max_buffer_samples = 4000
        self.samples_s1: List[List[int]] = []
        self.samples_s2: List[List[int]] = []
        self.first_buffered_idx = {1: 0, 2: 0}
        self.current_idx = {1: 0, 2: 0}
        
        # Fault injection flags
        self.inject_corrupt_crc_count = 0
        self.inject_duplicate_count = 0
        self.stop_sensor_for = {1: 0, 2: 0}

    def _generate_sample(self, sensor: int, idx: int) -> List[int]:
        if self.mode == "ramp":
            if sensor == 1:
                return [(3 * idx + c) % 8388608 for c in range(3)]
            else:
                return [(2 * idx + c) % 8388608 for c in range(2)]
        else:
            # Signal mode (realistic ECG & slow variation)
            if sensor == 1:
                # 60 bpm = 1 beat/sec = peak every 400 samples
                # 90 bpm = 1.5 beats/sec = peak every 266 samples
                # 72 bpm = 1.2 beats/sec = peak every 333 samples
                sec = idx // 400
                minute = (sec // 60) % 6
                interval = 400 if minute < 2 else (266 if minute < 4 else 333)
                phase = idx % interval
                # Sharp peak at phase == 0
                if phase == 0:
                    ch2 = 500000
                elif phase == 1 or phase == interval - 1:
                    ch2 = 100000
                else:
                    ch2 = 10000 + int(5000 * ((phase % 50) / 50.0))
                return [int(ch2 * 0.6), ch2, int(ch2 * 1.3)]
            else:
                return [400000 + (idx % 1000), 150000 + (idx % 500)]

    def handle_client(self, conn: socket.socket):
        buffer = bytearray()
        try:
            while self.running:
                # Read line
                nl_idx = buffer.find(b"\n")
                if nl_idx == -1:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    continue

                line = bytes(buffer[:nl_idx]).decode("utf-8")
                del buffer[: nl_idx + 1]
                if not line.strip():
                    continue

                try:
                    cmd = json.loads(line)
                except Exception:
                    continue

                if cmd.get("cmd") == "read":
                    sensor = cmd.get("sensor", 1)
                    from_index = cmd.get("from_index")
                    
                    req_idx = from_index if from_index is not None else self.current_idx[sensor]
                    count = 40  # send 40 samples (0.1s) per read
                    data = [self._generate_sample(sensor, req_idx + i) for i in range(count)]
                    
                    # Compute CRC on json data bytes
                    data_json_bytes = json.dumps(data).encode("utf-8")
                    computed_crc = f"{zlib.crc32(data_json_bytes) & 0xffffffff:08x}"

                    # Fault injection: Corrupt CRC
                    if self.inject_corrupt_crc_count > 0:
                        computed_crc = "deadbeef"
                        self.inject_corrupt_crc_count -= 1

                    reply = {
                        "session_id": self.session_id,
                        "sensor": sensor,
                        "first_index": req_idx,
                        "count": count,
                        "lost": [],
                        "session_end": False,
                        "crc32": computed_crc,
                        "data": data
                    }

                    reply_line = (json.dumps(reply) + "\n").encode("utf-8")
                    conn.sendall(reply_line)

                    # Fault injection: Duplicate
                    if self.inject_duplicate_count > 0:
                        conn.sendall(reply_line)
                        self.inject_duplicate_count -= 1

                    if from_index is None:
                        self.current_idx[sensor] += count

        except Exception:
            pass
        finally:
            conn.close()

    def start(self):
        self.running = True
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", self.port))
        self.server_sock.listen(1)
        
        def loop():
            while self.running:
                try:
                    conn, _ = self.server_sock.accept()
                    self.handle_client(conn)
                except Exception:
                    break

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.server_sock:
            self.server_sock.close()


if __name__ == "__main__":
    server = MockSensorServer(port=7100, mode="ramp")
    server.start()
    print("Mock simulator running on port 7100. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
