#!/usr/bin/env python3
"""Migrate data from a local SQLite database to MySQL.

Copies the tables managed by ``TaskRepository.initialize()`` from a
SQLite ``video_sum.db`` into a MySQL database created via ``open_database``
(the target database is auto-created with utf8mb4 when missing).

Usage:
    python scripts/migrate_sqlite_to_mysql.py \
        --sqlite /path/to/video_sum.db \
        --mysql mysql://user:password@host:3306/video_sum [--force]

The copy is idempotent only with --force (INSERT IGNORE); without it the
script aborts if any target table already contains rows, so a half-loaded
target is never silently mixed.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_dir in ("packages/core/src", "packages/infra/src", "apps/service/src"):
    path = str(REPO_ROOT / source_dir)
    if path not in sys.path:
        sys.path.insert(0, path)

from video_sum_infra.db import open_database  # noqa: E402
from video_sum_service.repository import TaskRepository  # noqa: E402

# Foreign-key-safe copy order: referenced tables load before their dependents.
TABLES = [
    "library_preferences",
    "video_assets",
    "video_folders",
    "video_folder_memberships",
    "video_collections",
    "video_collection_folder_memberships",
    "video_collection_task_batches",
    "tasks",
    "task_results",
    "task_events",
    "video_collection_items",
    "video_tags",
    "knowledge_index",
    "knowledge_conversations",
    "knowledge_messages",
    "knowledge_jobs",
    "knowledge_job_items",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, help="Path to the source video_sum.db")
    parser.add_argument("--mysql", required=True, help="Target MySQL URL, e.g. mysql://user:pass@host:3306/db")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow loading into non-empty tables (uses INSERT IGNORE).",
    )
    return parser.parse_args()


def source_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row[1]) for row in rows]


def count_rows(session, table: str) -> int:
    rows = session.execute(f"SELECT COUNT(*) AS count FROM {table}")
    return int(rows[0]["count"])


def main() -> int:
    args = parse_args()
    source_path = Path(args.sqlite)
    if not source_path.is_file():
        raise SystemExit(f"SQLite file not found: {source_path}")

    # Read-only source so a live service cannot race the copy.
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        target = open_database(args.mysql)
        try:
            repository = TaskRepository(target)
            repository.initialize()

            for table in TABLES:
                columns = source_columns(source, table)
                if not columns:
                    print(f"skip   {table} (missing in source)")
                    continue
                target_columns = target.table_columns(table)
                missing = [column for column in columns if column not in target_columns]
                if missing:
                    raise SystemExit(f"{table}: source columns missing in target schema: {missing}")

                existing = count_rows(target, table)
                if existing and not args.force:
                    raise SystemExit(
                        f"{table}: target already has {existing} row(s); re-run with --force to merge"
                    )
                verb = "INSERT IGNORE INTO" if args.force else "INSERT INTO"

                rows = source.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
                if rows:
                    placeholders = ", ".join("?" for _ in columns)
                    with target.cursor() as cursor:
                        cursor.executemany(
                            f"{verb} {table} ({', '.join(columns)}) VALUES ({placeholders})",
                            [tuple(row) for row in rows],
                        )
                print(f"copy   {table:36s} {len(rows):6d} rows")
        finally:
            target.close()
    finally:
        source.close()

    print("\nverification (source -> target row counts):")
    source2 = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    try:
        target = open_database(args.mysql)
        try:
            ok = True
            for table in TABLES:
                source_count = source2.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                try:
                    target_count = count_rows(target, table)
                except Exception:
                    target_count = "missing"
                status = "ok" if target_count == source_count else "MISMATCH"
                if status != "ok":
                    ok = False
                print(f"  {status:8s} {table:36s} {source_count:6d} -> {target_count}")
        finally:
            target.close()
    finally:
        source2.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
