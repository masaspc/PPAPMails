#!/usr/bin/env python3
"""cron: 期限切れファイル・DB削除スクリプト

crontab設定例:
  0 3 * * * /opt/secure-download/venv/bin/python /opt/secure-download/scripts/cleanup_expired.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import async_session
from app.services.cleanup import CleanupService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    async with async_session() as db:
        service = CleanupService(db)

        deleted = await service.cleanup_expired_transfers()
        logger.info("Deleted %d expired transfers", deleted)

        orphaned = await service.cleanup_orphaned_files()
        logger.info("Deleted %d orphaned files", orphaned)

        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
