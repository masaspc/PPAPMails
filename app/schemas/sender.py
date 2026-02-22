"""送信者向けスキーマ"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class RecipientOut(BaseModel):
    """受信者情報"""
    email: str
    recipient_type: str

    model_config = {"from_attributes": True}


class DownloadLogOut(BaseModel):
    """ダウンロードログ"""
    recipient_email: str
    downloaded_at: datetime
    ip_address: str | None
    user_agent: str | None

    model_config = {"from_attributes": True}


class AttachmentOut(BaseModel):
    """添付ファイル情報"""
    id: uuid.UUID
    original_filename: str
    file_size: int
    mime_type: str | None
    download_count: int
    max_downloads: int
    download_logs: list[DownloadLogOut] = []

    model_config = {"from_attributes": True}


class TransferListItem(BaseModel):
    """送信履歴一覧用"""
    id: uuid.UUID
    subject: str | None
    sent_at: datetime
    status: str
    expires_at: datetime
    recipient_count: int
    attachment_count: int

    model_config = {"from_attributes": True}


class TransferDetail(BaseModel):
    """送信詳細"""
    id: uuid.UUID
    original_message_id: str
    sender_email: str
    subject: str | None
    sent_at: datetime
    status: str
    expires_at: datetime
    recipients: list[RecipientOut]
    attachments: list[AttachmentOut]

    model_config = {"from_attributes": True}


class RevokeResponse(BaseModel):
    """URL無効化レスポンス"""
    success: bool
    message: str
