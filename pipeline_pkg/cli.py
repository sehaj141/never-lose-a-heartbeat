"""
CLI implementation for the required 'pipeline' command suite:
- pipeline status
- pipeline export --session ID --from device (or --from cloud)
- pipeline results --session ID
- pipeline start (daemon / service runner)
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
import urllib.request
from typing import Optional

from .storage import StorageEngine, DEFAULT_DB_PATH
from .collector import MockCollector
from .sync_manager import SyncManager


def cmd_status(args):
    storage = StorageEngine(args.db)
    mode = storage.get_meta("current_mode") or "offline"
    session_id = storage.get_meta("current_session_id")
    saved, in_cloud, backlog = storage.get_status_counts(session_id)

    status_dict = {
        "mode": mode,
        "samples_saved": saved,
        "samples_in_cloud": in_cloud,
        "backlog": backlog
    }
    sys.stdout.write(json.dumps(status_dict) + "\n")
    sys.stdout.flush()


def cmd_export(args):
    session_id = args.session
    if not session_id:
        sys.stderr.write("Error: --session ID is required\n")
        sys.exit(1)

    source = args.source
    if source == "cloud":
        cloud_url = os.environ.get("CLOUD_URL", "http://127.0.0.1:8080").rstrip("/")
        url = f"{cloud_url}/api/export?session_id={session_id}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                for line in resp:
                    sys.stdout.write(line.decode("utf-8"))
        except Exception as e:
            sys.stderr.write(f"Failed to fetch export from cloud: {e}\n")
            sys.exit(1)
    else:
        # from device
        storage = StorageEngine(args.db)
        for line in storage.export_data(session_id):
            sys.stdout.write(line + "\n")
    sys.stdout.flush()


def cmd_results(args):
    session_id = args.session
    if not session_id:
        sys.stderr.write("Error: --session ID is required\n")
        sys.exit(1)

    storage = StorageEngine(args.db)
    for line in storage.export_results(session_id):
        sys.stdout.write(line + "\n")
    sys.stdout.flush()


def cmd_start(args):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logging.info("Starting Never Lose a Heartbeat pipeline daemon...")

    storage = StorageEngine(args.db)
    cloud_url = os.environ.get("CLOUD_URL", args.cloud_url)
    mock_host = os.environ.get("MOCK_HOST", args.mock_host)
    mock_port = int(os.environ.get("MOCK_PORT", args.mock_port))

    collector = MockCollector(storage, host=mock_host, port=mock_port)
    sync_mgr = SyncManager(storage, cloud_url=cloud_url)

    # Start sync manager thread
    sync_thread = threading.Thread(target=sync_mgr.sync_loop, daemon=True)
    sync_thread.start()

    logging.info(f"Connecting to mock at {mock_host}:{mock_port} and cloud at {cloud_url}")
    try:
        while True:
            collector.run_once()
            # Brief yield to prevent pegging 100% CPU when socket has no immediate data
            time.sleep(0.002)
    except KeyboardInterrupt:
        logging.info("Shutting down pipeline daemon...")
    finally:
        sync_mgr.stop()
        storage.close()


def main():
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database file")

    parser = argparse.ArgumentParser(prog="pipeline", description="Never Lose a Heartbeat Data Pipeline", parents=[parent_parser])
    subparsers = parser.add_subparsers(dest="command")

    # 1. status
    subparsers.add_parser("status", parents=[parent_parser], help="Print current status as single JSON line")

    # 2. export
    p_export = subparsers.add_parser("export", parents=[parent_parser], help="Export samples and loss records as JSON lines")
    p_export.add_argument("--session", required=True, help="Session ID")
    p_export.add_argument(
        "--from",
        dest="source",
        choices=["device", "cloud"],
        default="device",
        help="Source to export from (device or cloud)"
    )

    # 3. results
    p_results = subparsers.add_parser("results", parents=[parent_parser], help="Print Section 3 outputs per window and mode")
    p_results.add_argument("--session", required=True, help="Session ID")

    # 4. start (daemon)
    p_start = subparsers.add_parser("start", parents=[parent_parser], help="Start the background pipeline daemon")
    p_start.add_argument("--mock-host", default="127.0.0.1", help="Mock service host")
    p_start.add_argument("--mock-port", default=7100, type=int, help="Mock service port")
    p_start.add_argument("--cloud-url", default="http://127.0.0.1:8080", help="Cloud backend URL")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "results":
        cmd_results(args)
    elif args.command == "start":
        cmd_start(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
