# Deliverable 5: 5-Minute Demonstration Video Note

**Project:** Never Lose a Heartbeat Data Pipeline  
**Candidate:** Sehaj (GitHub: `sehaj141`)  
**Repository:** https://github.com/sehaj141/never-lose-a-heartbeat  
**Video Duration:** Under 5 minutes (MP4)  

---

## Video Contents & Timestamps

The video demonstration was recorded following the official evaluation runbook:

* **0:00 – 1:00 (Baseline Online Mode):**
  * Demonstrates concurrent execution of `biosignal-mock`, `pipeline_pkg/cloud_server.py`, and `pipeline start`.
  * Verifies live streaming status using `pipeline status` showing `"mode": "online"` with real-time cloud data ingestion.

* **1:00 – 2:00 (Simulated Network Outage):**
  * Network connection to cloud server is severed.
  * Demonstrates the pipeline watchdog detecting connection failure and transitioning to `"mode": "offline"` within 10 seconds.
  * Demonstrates local persistence and growing backlog counter.

* **2:00 – 3:15 (Network Restoration & Catch-Up):**
  * Cloud server connectivity restored.
  * Demonstrates automatic transition back to `"mode": "online"` within 10 seconds.
  * Shows high-throughput backlog replay draining to 0 without dropped samples or duplicates.

* **3:15 – 4:00 (Process Kill Resilience):**
  * Abruptly terminates the pipeline daemon with `kill -9` (SIGKILL).
  * Restarts daemon and executes `pipeline status` to verify SQLite WAL crash recovery with zero corrupted records.

* **4:00 – 5:00 (Power Severance & Ground Truth Audit):**
  * Hard kernel reset simulation (`sysrq-trigger`).
  * Executes `pipeline export --from device` and verifies Section 3 window processing results via `pipeline results`.
