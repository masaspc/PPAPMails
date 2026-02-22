"""送信者向けルーター（Entra ID認証必須）"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import require_authenticated_user
from app.models.attachment import Attachment
from app.models.audit_log import AuditLog
from app.models.recipient import Recipient
from app.models.transfer import Transfer

router = APIRouter(prefix="/sender", tags=["sender"])


@router.get("/", response_class=HTMLResponse)
async def sender_history(
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """送信履歴一覧"""
    sender_email = user.get("email", "").lower()

    result = await db.execute(
        select(Transfer)
        .where(Transfer.sender_email == sender_email)
        .order_by(Transfer.sent_at.desc())
        .options(
            selectinload(Transfer.recipients),
            selectinload(Transfer.attachments),
        )
    )
    transfers = result.scalars().all()

    transfer_list = []
    for t in transfers:
        transfer_list.append({
            "id": t.id,
            "subject": t.subject,
            "sent_at": t.sent_at,
            "status": t.status,
            "expires_at": t.expires_at,
            "recipient_count": len(t.recipients),
            "attachment_count": len(t.attachments),
        })

    return request.app.state.templates.TemplateResponse(
        "sender/history.html",
        {"request": request, "user": user, "transfers": transfer_list},
    )


@router.get("/transfer/{transfer_id}", response_class=HTMLResponse)
async def sender_transfer_detail(
    transfer_id: str,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """送信詳細（DL状況・受信者別）"""
    sender_email = user.get("email", "").lower()

    try:
        tid = uuid.UUID(transfer_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="無効なIDです")

    result = await db.execute(
        select(Transfer)
        .where(Transfer.id == tid, Transfer.sender_email == sender_email)
        .options(
            selectinload(Transfer.recipients),
            selectinload(Transfer.attachments).selectinload(Attachment.download_logs),
        )
    )
    transfer = result.scalar_one_or_none()

    if not transfer:
        raise HTTPException(status_code=404, detail="送信が見つかりません")

    return request.app.state.templates.TemplateResponse(
        "sender/detail.html",
        {"request": request, "user": user, "transfer": transfer},
    )


@router.post("/transfer/{transfer_id}/revoke")
async def revoke_transfer(
    transfer_id: str,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """URL無効化（誤送信対策）"""
    sender_email = user.get("email", "").lower()

    try:
        tid = uuid.UUID(transfer_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="無効なIDです")

    result = await db.execute(
        select(Transfer).where(
            Transfer.id == tid, Transfer.sender_email == sender_email
        )
    )
    transfer = result.scalar_one_or_none()

    if not transfer:
        raise HTTPException(status_code=404, detail="送信が見つかりません")

    if transfer.status == "revoked":
        return {"success": False, "message": "既に無効化されています"}

    transfer.status = "revoked"

    # 監査ログ
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    audit = AuditLog(
        actor_email=sender_email,
        action="revoke_transfer",
        target_type="transfer",
        target_id=tid,
        details={"reason": "sender_revoked"},
        ip_address=client_ip or None,
    )
    db.add(audit)
    await db.flush()

    return {"success": True, "message": "ダウンロードURLを無効化しました"}
