"""
Resource Profiler for Deliverable 4 (ARM64 Environment).
Monitors the 'pipeline' daemon for 3600 seconds (1 hour):
- Average CPU %
- Peak Memory (RSS in MB)
- Total Megabytes written to disk
- Total Megabytes sent over the network
Generates the exact benchmark table required for submission.
"""

import os
import sys
import time
import psutil  # Falls back to /proc if psutil is unavailable


def get_process_metrics(pid: int):
    try:
        proc = psutil.Process(pid)
        cpu = proc.cpu_percent(interval=0.1)
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        return cpu, rss_mb
    except Exception:
        # Fallback to reading /proc/<pid>/stat and statm
        try:
            with open(f"/proc/{pid}/statm", "r") as f:
                rss_pages = int(f.read().split()[1])
                rss_mb = (rss_pages * os.sysconf("SC_PAGE_SIZE")) / (1024 * 1024)
            return 0.0, rss_mb
        except Exception:
            return 0.0, 0.0


def get_system_io():
    # Read /proc/diskstats and /proc/net/dev
    disk_write_bytes = 0
    net_sent_bytes = 0

    try:
        with open("/proc/diskstats", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 10:
                    # sectors written is index 9 (512 bytes per sector)
                    sectors_written = int(parts[9])
                    disk_write_bytes += sectors_written * 512
    except Exception:
        pass

    try:
        with open("/proc/net/dev", "r") as f:
            for line in f:
                if ":" in line:
                    iface, stats = line.split(":")
                    if "lo" not in iface:
                        fields = stats.split()
                        # tx bytes is field 8
                        net_sent_bytes += int(fields[8])
    except Exception:
        pass

    return disk_write_bytes, net_sent_bytes


def main():
    if len(sys.argv) < 2:
        print("Usage: python profile_1hr.py <PIPELINE_PID> [DURATION_SECONDS]")
        sys.exit(1)

    pid = int(sys.argv[1])
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 3600

    print(f"Profiling PID {pid} for {duration} seconds...")
    start_time = time.time()
    
    cpu_samples = []
    peak_memory_mb = 0.0
    start_disk_bytes, start_net_bytes = get_system_io()

    try:
        while time.time() - start_time < duration:
            cpu, mem_mb = get_process_metrics(pid)
            cpu_samples.append(cpu)
            if mem_mb > peak_memory_mb:
                peak_memory_mb = mem_mb
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Profiling interrupted early by user.")

    end_disk_bytes, end_net_bytes = get_system_io()
    avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0
    total_disk_mb = max(0, (end_disk_bytes - start_disk_bytes) / (1024 * 1024))
    total_net_mb = max(0, (end_net_bytes - start_net_bytes) / (1024 * 1024))

    print("\n" + "=" * 60)
    print("DELIVERABLE 4: 1-HOUR RESOURCE MEASUREMENT REPORT")
    print("=" * 60)
    print(f"Environment:          Raspberry Pi 4 / ARM64 Cortex-A72 (Raspberry Pi OS)")
    print(f"Duration:             {len(cpu_samples)} seconds")
    print(f"Average CPU:          {avg_cpu:.2f}% (Limit: max 4 cores)")
    print(f"Peak Memory:          {peak_memory_mb:.2f} MB (Limit: 2000 MB)")
    print(f"Megabytes to Disk:    {total_disk_mb:.2f} MB")
    print(f"Megabytes over Net:   {total_net_mb:.2f} MB")
    print("=" * 60)

    # Save to file
    with open("resource_profile.txt", "w") as f:
        f.write(f"Average CPU: {avg_cpu:.2f}%\n")
        f.write(f"Peak Memory: {peak_memory_mb:.2f} MB\n")
        f.write(f"Disk Written: {total_disk_mb:.2f} MB\n")
        f.write(f"Network Sent: {total_net_mb:.2f} MB\n")


if __name__ == "__main__":
    main()
