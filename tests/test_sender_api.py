"""送信者APIのテスト"""

import uuid
from datetime import datetime, timezone

import pytest

from app.schemas.sender import TransferListItem, TransferDetail, RevokeResponse


class TestSenderSchemas:
    """送信者向けスキーマのテスト"""

    def test_transfer_list_item(self):
        item = TransferListItem(
            id=uuid.uuid4(),
            subject="テストメール",
            sent_at=datetime.now(timezone.utc),
            status="active",
            expires_at=datetime.now(timezone.utc),
            recipient_count=3,
            attachment_count=2,
        )
        assert item.status == "active"
        assert item.recipient_count == 3

    def test_revoke_response(self):
        resp = RevokeResponse(success=True, message="無効化しました")
        assert resp.success is True
