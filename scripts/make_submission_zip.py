"""
Build clean submission ZIP package for Never Lose a Heartbeat assessment.
Excludes git histories, temporary databases, and bytecode caches.
"""

import os
import zipfile

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_ZIP_LOCAL = os.path.join(PROJECT_DIR, "Never_Lose_a_Heartbeat_Submission.zip")
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
OUTPUT_ZIP_DESKTOP = os.path.join(DESKTOP_DIR, "Never_Lose_a_Heartbeat_Submission.zip")

EXCLUDE_DIRS = {".git", "__pycache__"}
EXCLUDE_EXTS = {".db", ".db-wal", ".db-shm", ".pyc", ".zip"}


def build_zip(target_path: str):
    print(f"Creating archive: {target_path}...")
    with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PROJECT_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for file in files:
                _, ext = os.path.splitext(file)
                if ext in EXCLUDE_EXTS:
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, PROJECT_DIR)
                zipf.write(full_path, os.path.join("never-lose-a-heartbeat", rel_path))
                print(f"  + Added: {rel_path}")

    size_mb = os.path.getsize(target_path) / (1024 * 1024)
    print(f"Successfully created: {target_path} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    build_zip(OUTPUT_ZIP_LOCAL)
    if os.path.exists(DESKTOP_DIR):
        try:
            build_zip(OUTPUT_ZIP_DESKTOP)
        except Exception as e:
            print(f"Could not write to Desktop: {e}")
