"""認証コード生成・検証サービス"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.auth_code import AuthCode
from app.models.auth_session import AuthSession
from app.models.recipient import Recipient


class AuthService:
    """受信者の認証コード管理"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def is_valid_recipient(self, transfer_id: uuid.UUID, email: str) -> bool:
        """メールアドレスがこの送信の受信者に含まれるか確認"""
        result = await self.db.execute(
            select(Recipient).where(
                and_(
                    Recipient.transfer_id == transfer_id,
                    Recipient.email == email.lower(),
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def generate_auth_code(self, transfer_id: uuid.UUID, email: str) -> str:
        """6桁の認証コードを生成してDBに保存"""
        code = f"{secrets.randbelow(1000000):06d}"
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.auth_code_expiry_minutes
        )

        auth_code = AuthCode(
            transfer_id=transfer_id,
            email=email.lower(),
            code=code,
            expires_at=expires_at,
        )
        self.db.add(auth_code)
        await self.db.flush()

        return code

    async def verify_auth_code(
        self, transfer_id: uuid.UUID, email: str, code: str
    ) -> tuple[bool, str]:
        """認証コードを検証

        Returns:
            tuple[bool, str]: (成功したか, メッセージ)
        """
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(AuthCode)
            .where(
                and_(
                    AuthCode.transfer_id == transfer_id,
                    AuthCode.email == email.lower(),
                    AuthCode.used == False,  # noqa: E712
                    AuthCode.expires_at > now,
                )
            )
            .order_by(AuthCode.created_at.desc())
            .limit(1)
        )
        auth_code = result.scalar_one_or_none()

        if auth_code is None:
            return False, "認証コードが無効または期限切れです。再度リクエストしてください。"

        if auth_code.attempt_count >= settings.auth_code_max_attempts:
            return False, "認証コードの入力回数上限に達しました。再度リクエストしてください。"

        if auth_code.code != code:
            auth_code.attempt_count += 1
            await self.db.flush()
            remaining = settings.auth_code_max_attempts - auth_code.attempt_count
            return False, f"認証コードが正しくありません。残り{remaining}回入力できます。"

        auth_code.used = True
        await self.db.flush()
        return True, "認証に成功しました。"

    async def create_session(self, transfer_id: uuid.UUID, email: str) -> str:
        """認証セッションを作成してトークンを返す"""
        session_token = uuid.uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_expiry_days)

        auth_session = AuthSession(
            transfer_id=transfer_id,
            email=email.lower(),
            session_token=session_token,
            expires_at=expires_at,
        )
        self.db.add(auth_session)
        await self.db.flush()

        return str(session_token)

    async def validate_session(
        self, transfer_id: uuid.UUID, session_token: str
    ) -> str | None:
        """セッショントークンを検証し、有効ならメールアドレスを返す"""
        try:
            token_uuid = uuid.UUID(session_token)
        except ValueError:
            return None

        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(AuthSession).where(
                and_(
                    AuthSession.transfer_id == transfer_id,
                    AuthSession.session_token == token_uuid,
                    AuthSession.expires_at > now,
                )
            )
        )
        session = result.scalar_one_or_none()

        if session is None:
            return None
        return session.email
