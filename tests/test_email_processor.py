"""EmailProcessorのテスト"""

import email
import email.mime.base
import email.mime.multipart
import email.mime.text
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email_processor import _format_file_size, _parse_address_list


class TestHelperFunctions:
    """ヘルパー関数のテスト"""

    def test_format_file_size_bytes(self):
        assert _format_file_size(500) == "500 B"

    def test_format_file_size_kb(self):
        assert _format_file_size(2048) == "2.0 KB"

    def test_format_file_size_mb(self):
        assert _format_file_size(5 * 1024 * 1024) == "5.0 MB"

    def test_parse_address_list_simple(self):
        result = _parse_address_list("user@example.com")
        assert result == ["user@example.com"]

    def test_parse_address_list_with_name(self):
        result = _parse_address_list("John Doe <john@example.com>")
        assert result == ["john@example.com"]

    def test_parse_address_list_multiple(self):
        result = _parse_address_list(
            "alice@example.com, Bob <bob@example.com>, charlie@example.com"
        )
        assert result == ["alice@example.com", "bob@example.com", "charlie@example.com"]

    def test_parse_address_list_none(self):
        result = _parse_address_list(None)
        assert result == []

    def test_parse_address_list_empty(self):
        result = _parse_address_list("")
        assert result == []


class TestEmailParsing:
    """メールパースのテスト"""

    def test_create_test_email_with_attachment(self):
        """添付ファイル付きメールの構築テスト"""
        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = "sender@tbnet.jp"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "テスト添付ファイル"
        msg["Message-ID"] = "<test123@tbnet.jp>"

        body = email.mime.text.MIMEText("本文テスト", "plain", "utf-8")
        msg.attach(body)

        attachment = email.mime.base.MIMEBase("application", "pdf")
        attachment.set_payload(b"%PDF-1.4 test content")
        attachment.add_header("Content-Disposition", "attachment", filename="test.pdf")
        msg.attach(attachment)

        assert msg["From"] == "sender@tbnet.jp"
        assert msg["To"] == "recipient@example.com"
        assert msg["Subject"] == "テスト添付ファイル"

        parts = list(msg.walk())
        attachments = [
            p for p in parts if p.get_content_disposition() == "attachment"
        ]
        assert len(attachments) == 1
        assert attachments[0].get_filename() == "test.pdf"
