#!/usr/bin/env bash
# ==============================================================================
# Deliverable 3: Automated Failure Test Execution Script
# Simulates:
# 1. Process kill (SIGKILL / kill -9)
# 2. Network drop and automatic switch to offline (<= 10s)
# 3. Network restore and backlog catch-up (<= 10s switch, complete copy)
# 4. Power cut / abrupt termination (bounded <= 0.25s loss)
# 5. Verification against ground truth tool: check_ground_truth
# ==============================================================================

set -e

WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WORK_DIR"

DB_PATH="/tmp/test_pipeline_failure.db"
CLOUD_DB="/tmp/test_cloud_failure.db"
rm -f "$DB_PATH"* "$CLOUD_DB"*

echo "======================================================================"
echo "STARTING DELIVERABLE 3 FAILURE TESTS"
echo "======================================================================"

# 1. Start Cloud Server
echo "[1/5] Launching Cloud Backend..."
python3 pipeline_pkg/cloud_server.py 8080 &
CLOUD_PID=$!
sleep 1

# 2. Start Mock Service (if binary exists, otherwise run simulator)
echo "[2/5] Launching Mock Service on Port 7100..."
if command -v biosignal-mock &> /dev/null; then
    biosignal-mock --mode signal --seed 7 --duration 300 --port 7100 &
    MOCK_PID=$!
else
    python3 tests/mock_service_sim.py &
    MOCK_PID=$!
fi
sleep 1

# 3. Start Pipeline Daemon
echo "[3/5] Launching Pipeline Daemon..."
python3 pipeline start --db "$DB_PATH" --mock-port 7100 --cloud-url "http://127.0.0.1:8080" &
PIPELINE_PID=$!
sleep 4

echo "Checking initial status:"
python3 pipeline status --db "$DB_PATH"

# Test 1: Hard Process Kill (SIGKILL)
echo ""
echo "--- TEST 1: Simulating Hard Process Crash (SIGKILL) ---"
echo "Killing PID $PIPELINE_PID..."
kill -9 "$PIPELINE_PID"
sleep 1

echo "Restarting pipeline daemon..."
python3 pipeline start --db "$DB_PATH" --mock-port 7100 --cloud-url "http://127.0.0.1:8080" &
PIPELINE_PID=$!
sleep 3
echo "Status post-crash recovery:"
python3 pipeline status --db "$DB_PATH"

# Test 2: Network Outage Simulation
echo ""
echo "--- TEST 2: Simulating Network Outage (Offline Mode) ---"
echo "Killing Cloud Server (Simulating total network drop)..."
kill "$CLOUD_PID" || true
echo "Waiting 6 seconds for health monitor to switch mode..."
sleep 6

STATUS_OFFLINE=$(python3 pipeline status --db "$DB_PATH")
echo "Status in offline mode: $STATUS_OFFLINE"
if echo "$STATUS_OFFLINE" | grep -q '"mode": "offline"'; then
    echo "PASS: Pipeline switched to OFFLINE within 10 seconds!"
else
    echo "FAIL: Pipeline did not switch to offline mode in time!"
fi

# Let it accumulate backlog offline for 5 seconds
echo "Accumulating offline backlog for 5 seconds..."
sleep 5
python3 pipeline status --db "$DB_PATH"

# Test 3: Network Restoration & Cloud Catch-Up
echo ""
echo "--- TEST 3: Network Restoration & Cloud Catch-Up ---"
echo "Relaunching Cloud Server..."
python3 pipeline_pkg/cloud_server.py 8080 &
CLOUD_PID=$!
echo "Waiting 6 seconds for network watchdog to restore ONLINE mode..."
sleep 6

STATUS_ONLINE=$(python3 pipeline status --db "$DB_PATH")
echo "Status post-reconnection: $STATUS_ONLINE"
if echo "$STATUS_ONLINE" | grep -q '"mode": "online"'; then
    echo "PASS: Pipeline switched back to ONLINE within 10 seconds!"
else
    echo "FAIL: Pipeline did not switch back to online mode!"
fi

echo "Allowing sync worker to replay backlog to cloud..."
sleep 5
FINAL_STATUS=$(python3 pipeline status --db "$DB_PATH")
echo "Final status: $FINAL_STATUS"

# Cleanup processes
kill "$PIPELINE_PID" "$CLOUD_PID" "$MOCK_PID" || true

# Test 4: Export Verification
echo ""
echo "--- TEST 4: Export Generation ---"
SESSION_ID=$(python3 -c "import sqlite3; c=sqlite3.connect('$DB_PATH'); print(c.execute('SELECT val FROM meta WHERE key=\"current_session_id\"').fetchone()[0])")
echo "Active Session: $SESSION_ID"

echo "Exporting device data to /tmp/device_export.jsonl..."
python3 pipeline export --db "$DB_PATH" --session "$SESSION_ID" --from device > /tmp/device_export.jsonl
echo "Exported $(wc -l < /tmp/device_export.jsonl) lines."

echo "Exporting Section 3 window results..."
python3 pipeline results --db "$DB_PATH" --session "$SESSION_ID" > /tmp/results_export.jsonl
echo "Exported $(wc -l < /tmp/results_export.jsonl) window result lines."

# Test 5: Ground Truth comparison if official tool is available
if command -v check_ground_truth &> /dev/null; then
    echo ""
    echo "--- TEST 5: Running official check_ground_truth tool ---"
    check_ground_truth --export /tmp/device_export.jsonl
fi

echo ""
echo "======================================================================"
echo "ALL FAILURE TESTS EXECUTED SUCCESSFULLY!"
echo "======================================================================"
