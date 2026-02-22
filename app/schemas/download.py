"""ダウンロードポータル用スキーマ"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class AuthCodeRequest(BaseModel):
    """認証コードリクエスト"""
    email: EmailStr


class AuthCodeVerify(BaseModel):
    """認証コード検証"""
    email: EmailStr
    code: str


class AttachmentInfo(BaseModel):
    """添付ファイル情報（ダウンロードページ表示用）"""
    id: uuid.UUID
    original_filename: str
    file_size: int
    mime_type: str | None
    download_count: int
    max_downloads: int

    model_config = {"from_attributes": True}


class TransferInfo(BaseModel):
    """送信情報（ダウンロードページ表示用）"""
    sender_email: str
    subject: str | None
    sent_at: datetime
    expires_at: datetime
    attachments: list[AttachmentInfo]

    model_config = {"from_attributes": True}


class AuthCodeResponse(BaseModel):
    """認証コード送信レスポンス"""
    message: str


class VerifyResponse(BaseModel):
    """認証検証レスポンス"""
    success: bool
    message: str
    session_token: str | None = None
