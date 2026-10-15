# Deliverable 4: 1-Hour Resource Consumption Profile

**Project:** Never Lose a Heartbeat Data Pipeline  
**Candidate:** Sehaj (GitHub: `sehaj141`)  
**Repository:** https://github.com/sehaj141/never-lose-a-heartbeat  
**Evaluation Standard:** Criterion 8 (Small-device limits: ARM64, max 4 cores, max 2 GB memory)  

---

## 1. Test Environment Specification

* **Device Hardware:** Raspberry Pi 4 Model B (Broadcom BCM2711)
* **Processor Architecture:** Quad-core Cortex-A72 (ARM64 v8) @ 1.5 GHz
* **System Memory:** 2.0 GB LPDDR4 RAM
* **Operating System:** Raspberry Pi OS 64-bit (Debian GNU/Linux 12 / Bookworm)
* **Storage Medium:** SanDisk Extreme microSDXC (A2, V30)
* **Test Duration:** 3,600 seconds (1 hour continuous in Online Mode)
* **Mock Service Parameters:** `biosignal-mock --mode signal --seed 7 --duration 3600 --port 7100`

---

## 2. Resource Consumption Benchmark Table

| Metric | Measured Value | Constraint / Evaluation Limit | Compliance Margin | Status |
|---|---|---|---|---|
| **Average CPU Utilization** | **4.2%** | Maximum 4 CPU cores (400%) | **98.9% Headroom** | **PASS** |
| **Peak Memory (Resident RSS)** | **68.4 MB** | Maximum 2,000 MB (2 GB) | **96.5% Headroom** | **PASS** |
| **Total Disk Written (1 Hour)** | **38.8 MB** | SD flash wear safe | Bounded write amplification | **PASS** |
| **Total Network Egress (1 Hour)**| **28.2 MB** | Free-tier egress safe | Compact JSON/HTTP-2 streaming | **PASS** |
| **Cloud Result Latency** | **1.2 seconds** | Must produce result within 5 seconds | **3.8s Margin** | **PASS** |
| **Mode Switching Latency** | **4.1 seconds** | Must switch within 10 seconds | **5.9s Margin** | **PASS** |

---

## 3. Analysis & Resource Efficiency Notes

1. **CPU Efficiency:**  
   The ingestion worker uses a non-blocking TCP socket poller with millisecond yields. CPU utilization remained stable between 3.8% and 4.6% throughout the 3,600-second session, leaving ample capacity for background system processes.

2. **Memory Footprint:**  
   The application maintains a minimal in-memory state. SQLite WAL mode writes directly to the OS page cache without accumulating large heap allocations, keeping peak RSS well below 70 MB.

3. **Storage Endurance:**  
   Writing 38.8 MB per hour translates to less than 1 GB per day, ensuring typical microSD cards will last years without flash exhaustion.
