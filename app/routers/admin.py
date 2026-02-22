"""管理者向けルーター（Entra ID認証 + 管理者ロール必須）"""

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import require_admin_user
from app.models.attachment import Attachment
from app.models.audit_log import AuditLog
from app.models.download_log import DownloadLog
from app.models.excluded_domain import ExcludedDomain
from app.models.system_setting import SystemSetting
from app.models.transfer import Transfer
from app.schemas.admin import ExcludedDomainCreate, SystemSettingUpdate
from app.services.file_manager import FileManager

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """ダッシュボード"""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 統計取得
    total_transfers = (await db.execute(select(func.count(Transfer.id)))).scalar() or 0
    active_transfers = (
        await db.execute(
            select(func.count(Transfer.id)).where(Transfer.status == "active")
        )
    ).scalar() or 0
    total_downloads = (
        await db.execute(select(func.count(DownloadLog.id)))
    ).scalar() or 0
    total_files = (
        await db.execute(select(func.count(Attachment.id)))
    ).scalar() or 0
    transfers_today = (
        await db.execute(
            select(func.count(Transfer.id)).where(Transfer.created_at >= today_start)
        )
    ).scalar() or 0
    downloads_today = (
        await db.execute(
            select(func.count(DownloadLog.id)).where(DownloadLog.downloaded_at >= today_start)
        )
    ).scalar() or 0

    try:
        fm = FileManager()
        storage_used = fm.get_storage_usage_mb()
    except Exception:
        storage_used = 0.0

    stats = {
        "total_transfers": total_transfers,
        "active_transfers": active_transfers,
        "total_downloads": total_downloads,
        "total_files_stored": total_files,
        "storage_used_mb": round(storage_used, 2),
        "transfers_today": transfers_today,
        "downloads_today": downloads_today,
    }

    return request.app.state.templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "user": user, "stats": stats},
    )


@router.get("/transfers", response_class=HTMLResponse)
async def admin_transfers(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """全社送信履歴"""
    offset = (page - 1) * per_page
    result = await db.execute(
        select(Transfer)
        .options(selectinload(Transfer.recipients), selectinload(Transfer.attachments))
        .order_by(Transfer.sent_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    transfers = result.scalars().all()

    total = (await db.execute(select(func.count(Transfer.id)))).scalar() or 0

    return request.app.state.templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "user": user,
            "transfers": transfers,
            "page": page,
            "per_page": per_page,
            "total": total,
            "section": "transfers",
        },
    )


@router.get("/transfers/{transfer_id}", response_class=HTMLResponse)
async def admin_transfer_detail(
    transfer_id: str,
    request: Request,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """送信詳細"""
    try:
        tid = uuid.UUID(transfer_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="無効なIDです")

    result = await db.execute(
        select(Transfer)
        .where(Transfer.id == tid)
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


@router.get("/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """システム設定画面"""
    result = await db.execute(select(SystemSetting).order_by(SystemSetting.key))
    settings_list = result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        "admin/settings.html",
        {"request": request, "user": user, "settings": settings_list},
    )


@router.put("/settings")
async def update_settings(
    body: SystemSettingUpdate,
    request: Request,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """システム設定変更"""
    for key, value in body.settings.items():
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value

    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    audit = AuditLog(
        actor_email=user.get("email"),
        action="update_settings",
        target_type="system_setting",
        details={"updated_keys": list(body.settings.keys())},
        ip_address=client_ip or None,
    )
    db.add(audit)
    await db.flush()

    return {"success": True, "message": "設定を更新しました"}


@router.get("/excluded-domains", response_class=HTMLResponse)
async def excluded_domains_page(
    request: Request,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """除外ドメイン管理画面"""
    result = await db.execute(
        select(ExcludedDomain).order_by(ExcludedDomain.domain)
    )
    domains = result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        "admin/domains.html",
        {"request": request, "user": user, "domains": domains},
    )


@router.post("/excluded-domains")
async def add_excluded_domain(
    body: ExcludedDomainCreate,
    request: Request,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """除外ドメイン追加"""
    domain = ExcludedDomain(domain=body.domain.lower(), reason=body.reason)
    db.add(domain)

    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    audit = AuditLog(
        actor_email=user.get("email"),
        action="add_excluded_domain",
        target_type="excluded_domain",
        details={"domain": body.domain},
        ip_address=client_ip or None,
    )
    db.add(audit)
    await db.flush()

    return {"success": True, "message": f"ドメイン {body.domain} を除外リストに追加しました"}


@router.delete("/excluded-domains/{domain_id}")
async def delete_excluded_domain(
    domain_id: str,
    request: Request,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """除外ドメイン削除"""
    try:
        did = uuid.UUID(domain_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="無効なIDです")

    result = await db.execute(
        select(ExcludedDomain).where(ExcludedDomain.id == did)
    )
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="ドメインが見つかりません")

    domain_name = domain.domain
    await db.delete(domain)

    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    audit = AuditLog(
        actor_email=user.get("email"),
        action="delete_excluded_domain",
        target_type="excluded_domain",
        details={"domain": domain_name},
        ip_address=client_ip or None,
    )
    db.add(audit)
    await db.flush()

    return {"success": True, "message": f"ドメイン {domain_name} を除外リストから削除しました"}


@router.get("/audit-logs", response_class=HTMLResponse)
async def audit_logs_page(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    actor_email: str | None = None,
    action: str | None = None,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """監査ログ閲覧"""
    query = select(AuditLog).order_by(AuditLog.created_at.desc())

    if actor_email:
        query = query.where(AuditLog.actor_email == actor_email)
    if action:
        query = query.where(AuditLog.action == action)

    offset = (page - 1) * per_page
    result = await db.execute(query.offset(offset).limit(per_page))
    logs = result.scalars().all()

    count_query = select(func.count(AuditLog.id))
    if actor_email:
        count_query = count_query.where(AuditLog.actor_email == actor_email)
    if action:
        count_query = count_query.where(AuditLog.action == action)
    total = (await db.execute(count_query)).scalar() or 0

    return request.app.state.templates.TemplateResponse(
        "admin/audit.html",
        {
            "request": request,
            "user": user,
            "logs": logs,
            "page": page,
            "per_page": per_page,
            "total": total,
        },
    )


@router.get("/audit-logs/export")
async def export_audit_logs(
    request: Request,
    user: dict = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """監査ログCSVエクスポート"""
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc())
    )
    logs = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "実行者", "アクション", "対象種別", "対象ID",
        "詳細", "IPアドレス", "日時",
    ])
    for log in logs:
        writer.writerow([
            str(log.id),
            log.actor_email or "",
            log.action,
            log.target_type or "",
            str(log.target_id) if log.target_id else "",
            str(log.details) if log.details else "",
            str(log.ip_address) if log.ip_address else "",
            log.created_at.isoformat() if log.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )
