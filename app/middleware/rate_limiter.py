"""IPレート制限ミドルウェア"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import settings


class RateLimiter(BaseHTTPMiddleware):
    """IPアドレスベースのレート制限"""

    def __init__(self, app, max_requests: int | None = None, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests or settings.rate_limit_per_minute
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """クライアントIPを取得（X-Forwarded-For対応）"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup_old_requests(self, ip: str, now: float) -> None:
        """ウィンドウ外のリクエスト記録を削除"""
        cutoff = now - self.window_seconds
        self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # ヘルスチェックはレート制限対象外
        if request.url.path == "/internal/health":
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        now = time.time()

        self._cleanup_old_requests(client_ip, now)

        if len(self._requests[client_ip]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="リクエスト数が上限に達しました。しばらくしてから再度お試しください。",
            )

        self._requests[client_ip].append(now)
        return await call_next(request)
