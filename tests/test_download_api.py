"""ダウンロードAPIのテスト"""

import uuid

import pytest

from app.schemas.download import AuthCodeRequest, AuthCodeVerify


class TestDownloadSchemas:
    """ダウンロードスキーマのバリデーションテスト"""

    def test_auth_code_request_valid(self):
        req = AuthCodeRequest(email="user@example.com")
        assert req.email == "user@example.com"

    def test_auth_code_request_invalid_email(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AuthCodeRequest(email="not-an-email")

    def test_auth_code_verify_valid(self):
        verify = AuthCodeVerify(email="user@example.com", code="123456")
        assert verify.email == "user@example.com"
        assert verify.code == "123456"

    def test_auth_code_verify_invalid_email(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AuthCodeVerify(email="bad", code="123456")


class TestDownloadTokenValidation:
    """ダウンロードトークンのバリデーションテスト"""

    def test_valid_uuid_token(self):
        token = str(uuid.uuid4())
        parsed = uuid.UUID(token)
        assert str(parsed) == token

    def test_invalid_uuid_token(self):
        with pytest.raises(ValueError):
            uuid.UUID("not-a-uuid")

    def test_short_uuid_token(self):
        with pytest.raises(ValueError):
            uuid.UUID("12345")
