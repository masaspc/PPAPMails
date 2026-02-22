"""アプリケーション設定管理"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """環境変数から読み込む設定"""

    # アプリケーション
    app_name: str = "TBN Secure Download"
    app_env: str = "production"
    app_secret_key: str = "change-me-in-production"
    app_debug: bool = False
    portal_domain: str = "download.tbnet.jp"

    # データベース
    database_url: str = "postgresql+asyncpg://tbn_app:password@localhost:5432/tbn_secure_download"
    database_url_sync: str = "postgresql://tbn_app:password@localhost:5432/tbn_secure_download"

    # ファイルストレージ
    storage_path: str = "/var/tbn-secure-download/files"
    encryption_key: str = ""

    # Microsoft Graph API
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    graph_sender_email: str = "noreply@tbnet.jp"

    # Entra ID認証
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_redirect_uri: str = "https://download.tbnet.jp/auth/callback"
    admin_group_id: str = ""

    # メール処理
    max_file_size_mb: int = 50
    download_expiry_days: int = 30
    max_downloads: int = 10
    auth_code_expiry_minutes: int = 10
    auth_code_max_attempts: int = 5
    session_expiry_days: int = 14
    rate_limit_per_minute: int = 30

    # 監視
    teams_webhook_url: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
