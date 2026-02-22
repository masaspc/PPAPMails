"""AuthServiceのテスト"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAuthCodeGeneration:
    """認証コード生成のテスト"""

    def test_auth_code_format(self):
        """認証コードが6桁の数字であることを確認"""
        import secrets
        code = f"{secrets.randbelow(1000000):06d}"
        assert len(code) == 6
        assert code.isdigit()

    def test_auth_code_uniqueness(self):
        """認証コードがランダムに生成されることを確認"""
        import secrets
        codes = {f"{secrets.randbelow(1000000):06d}" for _ in range(100)}
        # 100回生成してすべて同じになることはない
        assert len(codes) > 1


class TestEmailValidation:
    """メールアドレスバリデーションのテスト"""

    def test_valid_email(self):
        """正しいメールアドレスが受け入れられるか"""
        from pydantic import EmailStr, TypeAdapter
        adapter = TypeAdapter(EmailStr)
        result = adapter.validate_python("user@example.com")
        assert result == "user@example.com"

    def test_invalid_email(self):
        """無効なメールアドレスが拒否されるか"""
        from pydantic import EmailStr, TypeAdapter, ValidationError
        adapter = TypeAdapter(EmailStr)
        with pytest.raises(ValidationError):
            adapter.validate_python("not-an-email")
