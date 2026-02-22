"""管理者向けスキーマ"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class DashboardStats(BaseModel):
    """ダッシュボード統計"""
    total_transfers: int
    active_transfers: int
    total_downloads: int
    total_files_stored: int
    storage_used_mb: float
    transfers_today: int
    downloads_today: int


class SystemSettingOut(BaseModel):
    """システム設定"""
    key: str
    value: str
    description: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SystemSettingUpdate(BaseModel):
    """システム設定更新"""
    settings: dict[str, str]


class ExcludedDomainOut(BaseModel):
    """除外ドメイン"""
    id: uuid.UUID
    domain: str
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExcludedDomainCreate(BaseModel):
    """除外ドメイン追加"""
    domain: str
    reason: str | None = None


class AuditLogOut(BaseModel):
    """監査ログ"""
    id: uuid.UUID
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    details: dict | None
    ip_address: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogFilter(BaseModel):
    """監査ログフィルター"""
    actor_email: str | None = None
    action: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: int = 1
    per_page: int = 50
