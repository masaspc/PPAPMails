"""送信履歴モデル"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    original_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # リレーション
    recipients: Mapped[list["Recipient"]] = relationship(  # noqa: F821
        back_populates="transfer", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(  # noqa: F821
        back_populates="transfer", cascade="all, delete-orphan"
    )
    auth_codes: Mapped[list["AuthCode"]] = relationship(  # noqa: F821
        back_populates="transfer", cascade="all, delete-orphan"
    )
    auth_sessions: Mapped[list["AuthSession"]] = relationship(  # noqa: F821
        back_populates="transfer", cascade="all, delete-orphan"
    )
