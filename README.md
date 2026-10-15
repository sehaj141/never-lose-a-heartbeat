# Never Lose a Heartbeat — Robust Edge Data Pipeline

A resilient, zero-silent-loss data pipeline engineered for medical telemetry on Raspberry Pi-class ARM64 hardware operating under hostile network environments and sudden power loss.

---

## 1. Quick Start on a Fresh Raspberry Pi Board

### 1-Step Installation
Clone the repository and run the automated installer:
```bash
git clone https://github.com/your-username/never-lose-a-heartbeat.git
cd never-lose-a-heartbeat
bash scripts/install.sh
```
This symlinks the `pipeline` executable into `/usr/local/bin/pipeline` and prepares `/var/lib/pipeline/` for WAL persistence.

---

## 2. Operating the Pipeline

### Starting the Pipeline Daemon
You can run the daemon manually or via `systemd`:

**Option A: Run in foreground / tmux:**
```bash
pipeline start --mock-host 127.0.0.1 --mock-port 7100 --cloud-url http://127.0.0.1:8080
```

**Option B: Production systemd daemon (auto-restarts on crash/reboot):**
```bash
sudo systemctl enable --now pipeline
sudo journalctl -u pipeline -f
```

---

## 3. Required Commands (Specification Section 4)

All commands are accessed via the unified `pipeline` executable:

### 1. `pipeline status`
Prints current mode, samples saved, samples in the cloud, and backlog as **one single JSON line**:
```bash
pipeline status
```
*Output:*
```json
{"mode": "online", "samples_saved": 120000, "samples_in_cloud": 119800, "backlog": 200}
```

### 2. `pipeline export --session ID --from device` (or `--from cloud`)
Exports full session data as newline-delimited JSON (samples first, followed by explicit loss intervals):
```bash
pipeline export --session 5f0c2a9e --from device > device_export.jsonl
pipeline export --session 5f0c2a9e --from cloud > cloud_export.jsonl
```
*Output Format:*
```json
{"sensor": 1, "index": 120000, "values": [720, 1200, 1560]}
{"sensor": 2, "index": 120000, "values": [400120, 150010]}
{"sensor": 2, "from_index": 4000, "to_index": 4399, "reason": "buffer_overflow"}
```

### 3. `pipeline results --session ID`
Outputs Section 3 processing outputs (one JSON line per 1-second window and mode):
```bash
pipeline results --session 5f0c2a9e
```
*Output Format:*
```json
{"window": 0, "mode": "online", "missing_1": 0, "missing_2": 0, "complete": true, "mean": {"sensor_1": [715.2, 1195.4, 1554.1], "sensor_2": [400050.1, 150002.3]}, "min": {"sensor_1": [680, 1140, 1490], "sensor_2": [399800, 149900]}, "max": {"sensor_1": [750, 1250, 1620], "sensor_2": [400300, 150120]}, "magnitude": 427258.4, "heart_rate": 60.0}
```

---

## 4. Free-Tier Cloud Backend Setup

In accordance with competition rules (*"Free services only. Using a paid service disqualifies the submission"*), the cloud service can be run locally or deployed for free on Fly.io, Cloudflare Workers, or AWS Free Tier:

### Running the Free Cloud Server
```bash
python3 pipeline_pkg/cloud_server.py 8080
```
This runs an asynchronous ingestion and real-time window analyzer processing batches in < 5 seconds and serving deduplicated exports.

---

## 5. Verification & Testing

### Running the Unit Test Suite
```bash
python3 tests/test_suite.py
```
Validates:
- Section 3 Heart-rate peak detector and refractory period
- CRC-32 extraction from raw JSON byte slices
- SQLite WAL deduplication and atomic commits
- Fault injection recovery (corrupted packets)

### Running Automated Failure Tests (Deliverable 3)
```bash
bash tests/test_failures.sh
```
Executes hard process kills (`kill -9`), network disconnection, offline window computation, network restoration, and invokes the official `check_ground_truth` tool.

---

## 6. Measuring 1-Hour Resource Metrics (Deliverable 4)
Run the monitoring script alongside the pipeline in online mode:
```bash
python3 scripts/profile_1hr.py <PIPELINE_PID> 3600
```
Outputs the official benchmark metrics:
- Average CPU %
- Peak RAM (MB)
- Megabytes written to disk
- Megabytes sent over network

---

## 7. Disclosures & Submission Metrics

* **AI Tools Disclosure:** In compliance with Section 5 rules (*"Disclose any AI tools used"*), AI assistance (Antigravity by Google DeepMind) was used for architectural prototyping, algorithmic implementation of Section 3 windowing logic, and test harness authoring.
* **Tested Environment:** Raspberry Pi 4 Model B (Broadcom BCM2711, Quad-core Cortex-A72 ARM64 @ 1.5GHz, 2GB LPDDR4, Raspberry Pi OS 64-bit).
* **Stated Power Cut Maximum Loss:** **0.25 seconds (at most 100 samples per sensor)**, strictly bounded by 250ms / 100-sample transactional `fdatasync()` barriers.
