"""Azure Functions: ヘルスチェック（HTTP Trigger）

Azure Front Door や Azure Monitor からのヘルスチェック用HTTPエンドポイント。
App Service の /internal/health と同等の機能を提供。
"""

import json
import logging
import sys
from pathlib import Path

import azure.functions as func

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

bp = func.Blueprint()


@bp.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """ヘルスチェックエンドポイント"""
    try:
        from sqlalchemy import text

        from app.database import async_session

        db_status = "ok"
        try:
            async with async_session() as db:
                await db.execute(text("SELECT 1"))
        except Exception:
            db_status = "error"

        overall = "ok" if db_status == "ok" else "error"
        status_code = 200 if overall == "ok" else 503

        return func.HttpResponse(
            json.dumps({
                "status": overall,
                "database": db_status,
                "storage": "ok",
                "version": "2.0.0",
            }),
            status_code=status_code,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Health check failed")
        return func.HttpResponse(
            json.dumps({"status": "error", "error": str(e)}),
            status_code=503,
            mimetype="application/json",
        )
