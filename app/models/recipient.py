"""受信者モデル"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Recipient(Base):
    __tablename__ = "recipients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    transfer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transfers.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recipient_type: Mapped[str] = mapped_column(String(5), nullable=False)  # to / cc / bcc
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    transfer: Mapped["Transfer"] = relationship(back_populates="recipients")  # noqa: F821
