"""ダウンロードポータル（受信者向け）ルーター"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.attachment import Attachment
from app.models.download_log import DownloadLog
from app.models.transfer import Transfer
from app.schemas.download import AuthCodeRequest, AuthCodeVerify
from app.services.auth_service import AuthService
from app.services.file_manager import FileManager
from app.services.notification import NotificationService

router = APIRouter(prefix="/d", tags=["download"])

SESSION_COOKIE_NAME = "tbn_session"


async def _get_transfer_by_token(
    download_token: str, db: AsyncSession
) -> tuple[Transfer, Attachment]:
    """ダウンロードトークンからTransferとAttachmentを取得"""
    try:
        token_uuid = uuid.UUID(download_token)
    except ValueError:
        raise HTTPException(status_code=404, detail="無効なURLです")

    result = await db.execute(
        select(Attachment)
        .options(selectinload(Attachment.transfer))
        .where(Attachment.download_url_token == token_uuid)
    )
    attachment = result.scalar_one_or_none()

    if attachment is None:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    transfer = attachment.transfer
    return transfer, attachment


@router.get("/{download_token}", response_class=HTMLResponse)
async def download_page(
    download_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """ダウンロードページ表示"""
    transfer, attachment = await _get_transfer_by_token(download_token, db)

    if transfer.status == "revoked":
        return request.app.state.templates.TemplateResponse(
            "download/revoked.html", {"request": request}
        )

    from datetime import datetime, timezone
    if transfer.expires_at < datetime.now(timezone.utc):
        return request.app.state.templates.TemplateResponse(
            "download/expired.html", {"request": request}
        )

    # セッションCookieで認証済みか確認
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        auth_service = AuthService(db)
        email = await auth_service.validate_session(transfer.id, session_token)
        if email:
            # 認証済み - ファイル一覧表示
            all_attachments_result = await db.execute(
                select(Attachment).where(Attachment.transfer_id == transfer.id)
            )
            all_attachments = all_attachments_result.scalars().all()
            return request.app.state.templates.TemplateResponse(
                "download/files.html",
                {
                    "request": request,
                    "transfer": transfer,
                    "attachments": all_attachments,
                    "email": email,
                    "download_token": download_token,
                },
            )

    # 未認証 - メールアドレス入力画面
    return request.app.state.templates.TemplateResponse(
        "download/index.html",
        {"request": request, "download_token": download_token, "transfer": transfer},
    )


@router.post("/{download_token}/request-code")
async def request_auth_code(
    download_token: str,
    body: AuthCodeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """認証コードリクエスト"""
    transfer, _ = await _get_transfer_by_token(download_token, db)

    auth_service = AuthService(db)

    if not await auth_service.is_valid_recipient(transfer.id, body.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このメールアドレスはダウンロード対象ではありません",
        )

    code = await auth_service.generate_auth_code(transfer.id, body.email)

    notification = NotificationService()
    await notification.send_auth_code_email(body.email, code)

    return {"message": f"{body.email} に認証コードを送信しました"}


@router.post("/{download_token}/verify")
async def verify_auth_code(
    download_token: str,
    body: AuthCodeVerify,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """認証コード検証"""
    transfer, _ = await _get_transfer_by_token(download_token, db)

    auth_service = AuthService(db)
    success, message = await auth_service.verify_auth_code(
        transfer.id, body.email, body.code
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)

    session_token = await auth_service.create_session(transfer.id, body.email)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,  # 14日
    )

    return {"success": True, "message": message, "session_token": session_token}


@router.get("/{download_token}/download/{attachment_id}")
async def download_file(
    download_token: str,
    attachment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """ファイルダウンロード（認証済み）"""
    transfer, _ = await _get_transfer_by_token(download_token, db)

    # 認証確認
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(status_code=401, detail="認証が必要です")

    auth_service = AuthService(db)
    email = await auth_service.validate_session(transfer.id, session_token)
    if not email:
        raise HTTPException(status_code=401, detail="セッションが無効です")

    # 添付ファイル取得
    try:
        att_uuid = uuid.UUID(attachment_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="無効なファイルIDです")

    result = await db.execute(
        select(Attachment).where(
            and_(
                Attachment.id == att_uuid,
                Attachment.transfer_id == transfer.id,
            )
        )
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    # ダウンロード回数チェック
    if attachment.download_count >= attachment.max_downloads:
        raise HTTPException(status_code=403, detail="ダウンロード回数の上限に達しています")

    # ファイル復号
    file_manager = FileManager()
    file_data = await file_manager.retrieve_file(attachment.stored_filename)

    # ダウンロードログ記録
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host

    download_log = DownloadLog(
        attachment_id=attachment.id,
        recipient_email=email,
        ip_address=client_ip or None,
        user_agent=request.headers.get("User-Agent"),
    )
    db.add(download_log)
    attachment.download_count += 1
    await db.flush()

    # ストリーミングレスポンス
    from io import BytesIO

    def iter_file():
        bio = BytesIO(file_data)
        while chunk := bio.read(8192):
            yield chunk

    return StreamingResponse(
        iter_file(),
        media_type=attachment.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{attachment.original_filename}"',
            "Content-Length": str(len(file_data)),
        },
    )
