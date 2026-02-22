#!/usr/bin/env python3
"""cron: PostgreSQL バックアップスクリプト

crontab設定例:
  0 2 * * * /opt/tbn-secure-download/venv/bin/python /opt/tbn-secure-download/scripts/db_backup.py

バックアップ先: /var/tbn-secure-download/backups/
保持期間: 30日
"""

import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BACKUP_DIR = os.environ.get("BACKUP_DIR", "/var/tbn-secure-download/backups")
DB_NAME = os.environ.get("DB_NAME", "tbn_secure_download")
DB_USER = os.environ.get("DB_USER", "tbn_app")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))


def create_backup() -> str | None:
    """pg_dumpでバックアップを作成"""
    backup_dir = Path(BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{DB_NAME}_{timestamp}.sql.gz"

    try:
        # pg_dump | gzip でバックアップ
        with open(backup_file, "wb") as f:
            dump = subprocess.Popen(
                ["pg_dump", "-U", DB_USER, "-d", DB_NAME, "--no-owner"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            gzip = subprocess.Popen(
                ["gzip"],
                stdin=dump.stdout,
                stdout=f,
                stderr=subprocess.PIPE,
            )
            dump.stdout.close()  # type: ignore[union-attr]
            gzip.communicate()
            dump.wait()

        if dump.returncode != 0:
            stderr = dump.stderr.read().decode() if dump.stderr else ""
            logger.error("pg_dump failed: %s", stderr)
            backup_file.unlink(missing_ok=True)
            return None

        size_mb = backup_file.stat().st_size / (1024 * 1024)
        logger.info("Backup created: %s (%.2f MB)", backup_file.name, size_mb)
        return str(backup_file)

    except Exception:
        logger.exception("Backup failed")
        backup_file.unlink(missing_ok=True)
        return None


def cleanup_old_backups() -> int:
    """古いバックアップを削除"""
    backup_dir = Path(BACKUP_DIR)
    if not backup_dir.exists():
        return 0

    now = datetime.now(timezone.utc)
    deleted = 0

    for f in backup_dir.glob(f"{DB_NAME}_*.sql.gz"):
        age_days = (now.timestamp() - f.stat().st_mtime) / 86400
        if age_days > RETENTION_DAYS:
            f.unlink()
            deleted += 1
            logger.info("Deleted old backup: %s", f.name)

    return deleted


def main() -> None:
    logger.info("Starting database backup")
    result = create_backup()
    if result:
        logger.info("Backup completed successfully")
    else:
        logger.error("Backup failed")

    deleted = cleanup_old_backups()
    if deleted:
        logger.info("Cleaned up %d old backups", deleted)


if __name__ == "__main__":
    main()
