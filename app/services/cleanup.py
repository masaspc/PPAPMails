"""期限切れファイル・DB自動削除サービス"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attachment import Attachment
from app.models.transfer import Transfer
from app.services.file_manager import FileManager

logger = logging.getLogger(__name__)


class CleanupService:
    """期限切れデータのクリーンアップ"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.file_manager = FileManager()

    async def cleanup_expired_transfers(self) -> int:
        """期限切れのTransferとそれに紐づくファイルを削除

        Returns:
            削除したTransfer数
        """
        now = datetime.now(timezone.utc)

        # 期限切れのTransferを取得
        result = await self.db.execute(
            select(Transfer).where(Transfer.expires_at < now)
        )
        expired_transfers = result.scalars().all()

        deleted_count = 0
        for transfer in expired_transfers:
            # 紐づく添付ファイルの物理削除
            attachments_result = await self.db.execute(
                select(Attachment).where(Attachment.transfer_id == transfer.id)
            )
            attachments = attachments_result.scalars().all()

            for attachment in attachments:
                try:
                    await self.file_manager.delete_file(attachment.stored_filename)
                except Exception:
                    logger.warning(
                        "Failed to delete file: %s", attachment.stored_filename
                    )

            # DBからCASCADE削除
            await self.db.delete(transfer)
            deleted_count += 1

        await self.db.flush()
        logger.info("Cleaned up %d expired transfers", deleted_count)
        return deleted_count

    async def cleanup_orphaned_files(self) -> int:
        """DBに紐づかない孤立ファイルを削除

        Returns:
            削除したファイル数
        """
        # DBに登録されたファイル名一覧を取得
        result = await self.db.execute(select(Attachment.stored_filename))
        db_filenames = {row[0] for row in result.all()}

        if settings.storage_backend == "azure_blob":
            return await self._cleanup_orphaned_blobs(db_filenames)
        else:
            return await self._cleanup_orphaned_local(db_filenames)

    async def _cleanup_orphaned_blobs(self, db_filenames: set[str]) -> int:
        """Azure Blob Storage の孤立ファイルを削除"""
        blob_names = await self.file_manager.list_blobs()
        deleted_count = 0
        for blob_name in blob_names:
            if blob_name not in db_filenames:
                await self.file_manager.delete_file(blob_name)
                deleted_count += 1
                logger.info("Deleted orphaned blob: %s", blob_name)
        return deleted_count

    async def _cleanup_orphaned_local(self, db_filenames: set[str]) -> int:
        """ローカルディスクの孤立ファイルを削除"""
        from pathlib import Path

        storage_path = Path(settings.storage_path)
        if not storage_path.exists():
            return 0

        deleted_count = 0
        for file_path in storage_path.iterdir():
            if file_path.is_file() and file_path.name not in db_filenames:
                file_path.unlink()
                deleted_count += 1
                logger.info("Deleted orphaned file: %s", file_path.name)

        return deleted_count
