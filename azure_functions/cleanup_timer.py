"""Azure Functions: 期限切れファイル・DB自動削除

Timer Trigger で毎日3:00 (JST) に実行。
"""

import asyncio
import logging
import sys
from pathlib import Path

import azure.functions as func

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

bp = func.Blueprint()


@bp.timer_trigger(
    schedule="0 0 18 * * *",  # UTC 18:00 = JST 03:00
    arg_name="timer",
    run_on_startup=False,
)
async def cleanup_timer(timer: func.TimerRequest) -> None:
    """期限切れTransferとファイルを定期削除"""
    logger.info("Cleanup timer triggered")

    try:
        from app.database import async_session
        from app.services.cleanup import CleanupService

        async with async_session() as db:
            service = CleanupService(db)

            deleted = await service.cleanup_expired_transfers()
            logger.info("Deleted %d expired transfers", deleted)

            orphaned = await service.cleanup_orphaned_files()
            logger.info("Deleted %d orphaned files", orphaned)

            await db.commit()

    except Exception:
        logger.exception("Cleanup failed")
