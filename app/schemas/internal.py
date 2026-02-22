"""内部API用スキーマ"""

from pydantic import BaseModel


class EmailProcessRequest(BaseModel):
    """メール処理リクエスト（Postfixからのトリガー）"""
    raw_email_path: str


class EmailProcessResponse(BaseModel):
    """メール処理レスポンス"""
    success: bool
    message: str
    transfer_id: str | None = None


class HealthResponse(BaseModel):
    """ヘルスチェックレスポンス"""
    status: str
    database: str
    storage: str
    version: str = "1.0.0"
