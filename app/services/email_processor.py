"""メール受信・添付分離・再構築サービス"""

import email
import email.policy
import logging
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attachment import Attachment
from app.models.recipient import Recipient
from app.models.transfer import Transfer
from app.services.file_manager import FileManager
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)


def _format_file_size(size_bytes: int) -> str:
    """ファイルサイズを人間が読みやすい形式に変換"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _parse_address_list(header_value: str | None) -> list[str]:
    """メールヘッダーのアドレスリストをパースする"""
    if not header_value:
        return []
    addresses = []
    for part in header_value.split(","):
        part = part.strip()
        if "<" in part and ">" in part:
            addr = part[part.index("<") + 1 : part.index(">")]
        else:
            addr = part
        addr = addr.strip().lower()
        if addr and "@" in addr:
            addresses.append(addr)
    return addresses


class EmailProcessor:
    """メール受信から再構築メール送信までの処理"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.file_manager = FileManager()
        self.notification = NotificationService()

    async def process_email(self, raw_email_path: str) -> uuid.UUID:
        """生のメールファイルを処理する

        Args:
            raw_email_path: 生メールファイルのパス

        Returns:
            作成されたTransferのID
        """
        raw_path = Path(raw_email_path)
        if not raw_path.exists():
            raise FileNotFoundError(f"Email file not found: {raw_email_path}")

        with open(raw_path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)

        return await self._process_message(msg)

    async def process_email_bytes(self, raw_data: bytes) -> uuid.UUID:
        """生のメールバイトデータを処理する"""
        msg = email.message_from_bytes(raw_data, policy=email.policy.default)
        return await self._process_message(msg)

    async def _process_message(self, msg: EmailMessage) -> uuid.UUID:
        """パース済みメールメッセージを処理"""
        sender = msg.get("From", "")
        if "<" in sender and ">" in sender:
            sender_email = sender[sender.index("<") + 1 : sender.index(">")].lower()
        else:
            sender_email = sender.strip().lower()

        subject = msg.get("Subject", "(件名なし)")
        message_id = msg.get("Message-ID", f"<{uuid.uuid4()}@local>")

        to_addrs = _parse_address_list(msg.get("To"))
        cc_addrs = _parse_address_list(msg.get("Cc"))
        bcc_addrs = _parse_address_list(msg.get("Bcc"))

        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.download_expiry_days)

        # Transfer作成
        transfer = Transfer(
            original_message_id=message_id,
            sender_email=sender_email,
            subject=subject,
            expires_at=expires_at,
        )
        self.db.add(transfer)
        await self.db.flush()

        # 受信者登録
        for addr in to_addrs:
            self.db.add(Recipient(
                transfer_id=transfer.id, email=addr, recipient_type="to"
            ))
        for addr in cc_addrs:
            self.db.add(Recipient(
                transfer_id=transfer.id, email=addr, recipient_type="cc"
            ))
        for addr in bcc_addrs:
            self.db.add(Recipient(
                transfer_id=transfer.id, email=addr, recipient_type="bcc"
            ))
        await self.db.flush()

        # 添付ファイル分離と保存
        attachments_data = []
        body_text = ""

        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()

            if disposition == "attachment" or (
                disposition == "inline" and part.get_filename()
            ):
                filename = part.get_filename() or "unnamed_file"
                file_data = part.get_payload(decode=True)
                if file_data is None:
                    continue

                stored_filename, file_size = await self.file_manager.store_file(
                    file_data, filename
                )
                download_token = uuid.uuid4()

                attachment = Attachment(
                    transfer_id=transfer.id,
                    original_filename=filename,
                    stored_filename=stored_filename,
                    file_size=file_size,
                    mime_type=content_type,
                    download_url_token=download_token,
                    max_downloads=settings.max_downloads,
                )
                self.db.add(attachment)

                attachments_data.append({
                    "filename": filename,
                    "size": _format_file_size(file_size),
                    "token": str(download_token),
                })
            elif content_type == "text/plain" and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_text = payload.decode(charset, errors="replace")
            elif content_type == "text/html" and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_text = payload.decode(charset, errors="replace")

        await self.db.flush()

        if not body_text:
            body_text = ""

        # 再構築メール送信
        if attachments_data:
            await self.notification.send_download_notification(
                to_recipients=to_addrs,
                cc_recipients=cc_addrs,
                bcc_recipients=bcc_addrs,
                original_subject=subject,
                original_body=body_text,
                sender_email=sender_email,
                download_links=attachments_data,
            )

        logger.info(
            "Processed email from %s with %d attachments (transfer_id=%s)",
            sender_email,
            len(attachments_data),
            transfer.id,
        )

        return transfer.id
