"""管理者APIのテスト"""

import uuid
from datetime import datetime, timezone

import pytest

from app.schemas.admin import (
    DashboardStats,
    ExcludedDomainCreate,
    SystemSettingUpdate,
    AuditLogFilter,
)


class TestAdminSchemas:
    """管理者向けスキーマのテスト"""

    def test_dashboard_stats(self):
        stats = DashboardStats(
            total_transfers=100,
            active_transfers=80,
            total_downloads=500,
            total_files_stored=200,
            storage_used_mb=1024.5,
            transfers_today=10,
            downloads_today=25,
        )
        assert stats.total_transfers == 100
        assert stats.storage_used_mb == 1024.5

    def test_system_setting_update(self):
        update = SystemSettingUpdate(
            settings={"max_file_size_mb": "100", "max_downloads": "20"}
        )
        assert len(update.settings) == 2
        assert update.settings["max_file_size_mb"] == "100"

    def test_excluded_domain_create(self):
        domain = ExcludedDomainCreate(domain="example.com", reason="テスト")
        assert domain.domain == "example.com"

    def test_excluded_domain_create_no_reason(self):
        domain = ExcludedDomainCreate(domain="example.com")
        assert domain.reason is None

    def test_audit_log_filter_defaults(self):
        f = AuditLogFilter()
        assert f.page == 1
        assert f.per_page == 50
        assert f.actor_email is None

    def test_audit_log_filter_custom(self):
        f = AuditLogFilter(
            actor_email="admin@tbnet.jp",
            action="revoke_transfer",
            page=2,
            per_page=25,
        )
        assert f.actor_email == "admin@tbnet.jp"
        assert f.page == 2


class TestInternalSchemas:
    """内部APIスキーマのテスト"""

    def test_health_response(self):
        from app.schemas.internal import HealthResponse
        resp = HealthResponse(status="ok", database="ok", storage="ok")
        assert resp.status == "ok"
        assert resp.version == "1.0.0"

    def test_email_process_response(self):
        from app.schemas.internal import EmailProcessResponse
        resp = EmailProcessResponse(
            success=True,
            message="処理完了",
            transfer_id=str(uuid.uuid4()),
        )
        assert resp.success is True
