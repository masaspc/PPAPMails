"""内部API（メール処理デーモン・ヘルスチェック用）ルーター"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas.internal import EmailProcessRequest, EmailProcessResponse, HealthResponse
from app.services.email_processor import EmailProcessor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/process-email", response_model=EmailProcessResponse)
async def process_email(
    body: EmailProcessRequest,
    db: AsyncSession = Depends(get_db),
):
    """Postfixからのメール処理トリガー"""
    processor = EmailProcessor(db)

    try:
        transfer_id = await processor.process_email(body.raw_email_path)
        return EmailProcessResponse(
            success=True,
            message="メールを処理しました",
            transfer_id=str(transfer_id),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Failed to process email")
        raise HTTPException(status_code=500, detail="メール処理中にエラーが発生しました")


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """ヘルスチェック（LB用）"""
    # DB接続確認
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    # ストレージ確認
    storage_status = "ok"
    storage_path = Path(settings.storage_path)
    if not storage_path.exists():
        storage_status = "warning"

    overall = "ok" if db_status == "ok" else "error"

    return HealthResponse(
        status=overall,
        database=db_status,
        storage=storage_status,
    )
