"""テスト用共通フィクスチャ"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

# テスト用に環境変数を設定
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("STORAGE_PATH", "/tmp/tbn-test-files")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///")


@pytest.fixture
def sample_transfer_data():
    """テスト用Transfer データ"""
    return {
        "original_message_id": "<test@example.com>",
        "sender_email": "sender@tbnet.jp",
        "subject": "テストメール",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
    }


@pytest.fixture
def sample_recipient_data():
    """テスト用Recipient データ"""
    return {
        "email": "recipient@example.com",
        "recipient_type": "to",
    }


@pytest.fixture
def sample_attachment_data():
    """テスト用Attachment データ"""
    return {
        "original_filename": "test.pdf",
        "stored_filename": "abc123_test.pdf.enc",
        "file_size": 1024,
        "mime_type": "application/pdf",
        "download_url_token": uuid.uuid4(),
        "max_downloads": 10,
    }
