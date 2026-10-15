"""
Comprehensive Test Suite for Never Lose a Heartbeat pipeline.
Validates:
1. Section 3 Heart-rate and peak detection algorithm against edge cases
2. CRC-32 extraction and validation on mock protocol format
3. Storage durability, deduplication, and export format
4. End-to-end integration with MockSensorServer
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pipeline_pkg.analyzer import compute_peaks, process_window
from pipeline_pkg.collector import extract_data_slice_and_crc, MockCollector
from pipeline_pkg.storage import StorageEngine
from tests.mock_service_sim import MockSensorServer


class TestAnalyzer(unittest.TestCase):
    def test_peak_detection_and_heart_rate(self):
        # Generate 6 seconds (2400 samples) of synthetic ECG at 60 bpm (peak every 400 samples)
        samples_s1 = {}
        samples_s2 = {}
        
        # Peaks placed at index 400, 800, 1200, 1600, 2000
        # Notice: peak i requires 800 samples before it!
        # So peak at 800 has [0..799] before it. Peak at 400 has only 400 before it (not a valid peak by rule 1).
        # Peaks should be at 800, 1200, 1600, 2000.
        for i in range(2400):
            # Baseline is 1000
            val_ch2 = 1000
            if i in [800, 1200, 1600, 2000]:
                val_ch2 = 50000  # Sharp peak
            elif i in [799, 801, 1199, 1201, 1599, 1601, 1999, 2001]:
                val_ch2 = 2000
            
            samples_s1[i] = [int(val_ch2 * 0.6), val_ch2, int(val_ch2 * 1.3)]
            samples_s2[i] = [400000, 150000]

        ch2_map = {i: samples_s1[i][1] for i in samples_s1}
        peaks, last_peak = compute_peaks(ch2_map, 0, 2399)
        
        # Verify peaks found
        self.assertIn(800, peaks)
        self.assertIn(1200, peaks)
        self.assertIn(1600, peaks)
        self.assertIn(2000, peaks)
        self.assertNotIn(400, peaks)  # Less than 800 samples of history!

        # Process window 5 (samples 2000 to 2399).
        # Trailing 5 seconds are window 1 to 5: samples 400*(5-4) = 400 to 400*(5+1)-1 = 2399.
        # Peaks in this range: 800, 1200, 1600, 2000.
        # Consecutive gaps: (1200-800)/400 = 1.0s, (1600-1200)/400 = 1.0s, (2000-1600)/400 = 1.0s.
        # Mean gap = 1.0s. Heart rate = 60 / 1.0 = 60.0 bpm!
        res_w5 = process_window(5, samples_s1, samples_s2, mode="online")
        self.assertEqual(res_w5["heart_rate"], 60.0)
        self.assertTrue(res_w5["complete"])
        self.assertEqual(res_w5["missing_1"], 0)
        self.assertEqual(res_w5["missing_2"], 0)
        self.assertAlmostEqual(res_w5["magnitude"], 427200.2, places=1)


class TestProtocolAndCRC(unittest.TestCase):
    def test_crc_verification(self):
        sample_data = [[720, 1200, 1560], [708, 1180, 1534]]
        data_text = json.dumps(sample_data)
        crc_val = f"{zlib.crc32(data_text.encode('utf-8')) & 0xffffffff:08x}"
        
        raw_msg = (
            f'{{"session_id": "sess1", "sensor": 1, "first_index": 0, "count": 2, '
            f'"lost": [], "session_end": false, "crc32": "{crc_val}", "data": {data_text}}}\n'
        ).encode("utf-8")

        calc_crc, exp_crc, parsed = extract_data_slice_and_crc(raw_msg)
        self.assertEqual(calc_crc, exp_crc)
        self.assertEqual(parsed["session_id"], "sess1")

    def test_corrupt_crc_detection(self):
        sample_data = [[720, 1200, 1560]]
        data_text = json.dumps(sample_data)
        bad_crc = "12345678"
        
        raw_msg = (
            f'{{"session_id": "sess1", "sensor": 1, "first_index": 0, "count": 1, '
            f'"lost": [], "session_end": false, "crc32": "{bad_crc}", "data": {data_text}}}\n'
        ).encode("utf-8")

        calc_crc, exp_crc, _ = extract_data_slice_and_crc(raw_msg)
        self.assertNotEqual(calc_crc, exp_crc)


class TestStorageEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_pipeline.db")
        self.storage = StorageEngine(self.db_path)

    def tearDown(self):
        self.storage.close()
        shutil.rmtree(self.test_dir)

    def test_deduplication_and_loss(self):
        sess = "s123"
        self.storage.start_session_if_new(sess)
        
        # Insert 10 samples
        self.storage.record_samples(sess, 1, 0, [[i, i*2, i*3] for i in range(10)])
        # Re-insert overlapping samples (0..4) - must be ignored without duplication
        self.storage.record_samples(sess, 1, 0, [[i, i*2, i*3] for i in range(5)])

        saved, _, backlog = self.storage.get_status_counts(sess)
        self.assertEqual(saved, 10)
        self.assertEqual(backlog, 10)

        # Log an explicit loss
        self.storage.record_loss(sess, 1, 10, 19, "buffer_overflow")

        # Verify export format
        export_lines = list(self.storage.export_data(sess))
        self.assertEqual(len(export_lines), 11)  # 10 samples + 1 loss
        last_obj = json.loads(export_lines[-1])
        self.assertEqual(last_obj["reason"], "buffer_overflow")
        self.assertEqual(last_obj["from_index"], 10)
        self.assertEqual(last_obj["to_index"], 19)


class TestEndToEndIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "e2e_pipeline.db")
        self.storage = StorageEngine(self.db_path)
        self.mock_server = MockSensorServer(port=7199, mode="ramp")
        self.mock_server.start()
        time.sleep(0.1)

    def tearDown(self):
        self.mock_server.stop()
        self.storage.close()
        shutil.rmtree(self.test_dir)

    def test_mock_ingestion_and_crc_retry(self):
        collector = MockCollector(self.storage, host="127.0.0.1", port=7199)
        # Poll 5 times (should collect 200 samples per sensor)
        for _ in range(5):
            collector.poll_sensor(1)
            collector.poll_sensor(2)
        
        saved, _, backlog = self.storage.get_status_counts(collector.current_session_id)
        self.assertEqual(saved, 400)  # 200 for sensor 1 + 200 for sensor 2
        self.assertEqual(backlog, 400)

        # Test corrupt CRC fault recovery
        self.mock_server.inject_corrupt_crc_count = 1
        success = collector.poll_sensor(1)
        self.assertTrue(success)  # Successfully caught corruption and re-read


if __name__ == "__main__":
    unittest.main()
