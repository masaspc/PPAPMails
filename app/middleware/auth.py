"""Entra ID認証ミドルウェア（送信者・管理者画面用）"""

import logging
from urllib.parse import urlencode

import httpx
import msal
from fastapi import HTTPException, Request, status
from starlette.responses import RedirectResponse

from app.config import settings

logger = logging.getLogger(__name__)

AUTHORITY = f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
SCOPES = ["User.Read"]


def _get_msal_app() -> msal.ConfidentialClientApplication:
    """MSAL アプリケーションインスタンスを取得"""
    return msal.ConfidentialClientApplication(
        settings.entra_client_id,
        authority=AUTHORITY,
        client_credential=settings.entra_client_secret,
    )


def get_login_url(redirect_path: str = "/auth/callback") -> str:
    """Entra IDログインURLを生成"""
    app = _get_msal_app()
    auth_url = app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=settings.entra_redirect_uri,
    )
    return auth_url


async def exchange_code_for_token(code: str) -> dict:
    """認可コードをトークンに交換"""
    app = _get_msal_app()
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=settings.entra_redirect_uri,
    )
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {result.get('error_description', 'Unknown error')}",
        )
    return result


async def get_user_info(access_token: str) -> dict:
    """Graph APIからユーザー情報を取得"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to fetch user info",
        )
    return response.json()


async def check_admin_group_membership(access_token: str) -> bool:
    """ユーザーが管理者グループに所属しているか確認"""
    if not settings.admin_group_id:
        return False

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://graph.microsoft.com/v1.0/me/memberOf",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
    if response.status_code != 200:
        return False

    groups = response.json().get("value", [])
    return any(g.get("id") == settings.admin_group_id for g in groups)


async def require_authenticated_user(request: Request) -> dict:
    """認証済みユーザーを要求するDependency"""
    user = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証が必要です",
        )
    return user


async def require_admin_user(request: Request) -> dict:
    """管理者ユーザーを要求するDependency"""
    user = await require_authenticated_user(request)
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理者権限が必要です",
        )
    return user
