"""FastAPI アプリケーションエントリポイント"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.middleware.auth import (
    check_admin_group_membership,
    exchange_code_for_token,
    get_login_url,
    get_user_info,
)
from app.middleware.rate_limiter import RateLimiter
from app.routers import admin, download, internal, sender

logging.basicConfig(
    level=logging.DEBUG if settings.app_debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs" if settings.app_debug else None,
    redoc_url=None,
)

# ミドルウェア
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret_key)
app.add_middleware(RateLimiter)

# テンプレートエンジン設定
from jinja2 import Environment, FileSystemLoader

templates_dir = Path(__file__).parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)


class TemplateRenderer:
    """Jinja2テンプレートレンダリングのラッパー"""

    def __init__(self, env: Environment):
        self.env = env

    def TemplateResponse(self, template_name: str, context: dict):
        from fastapi.responses import HTMLResponse

        template = self.env.get_template(template_name)
        html = template.render(**context)
        return HTMLResponse(html)


app.state.templates = TemplateRenderer(jinja_env)

# ルーター登録
app.include_router(download.router)
app.include_router(sender.router)
app.include_router(admin.router)
app.include_router(internal.router)


# Entra ID認証コールバック
@app.get("/auth/login")
async def auth_login(request: Request, next: str = "/sender/"):
    """Entra IDログインへリダイレクト"""
    request.session["auth_next"] = next
    login_url = get_login_url()
    return RedirectResponse(url=login_url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = ""):
    """Entra ID認証コールバック"""
    if not code:
        return RedirectResponse(url="/auth/login")

    token_result = await exchange_code_for_token(code)
    access_token = token_result.get("access_token")
    if not access_token:
        return RedirectResponse(url="/auth/login")

    user_info = await get_user_info(access_token)
    is_admin = await check_admin_group_membership(access_token)

    request.session["user"] = {
        "email": user_info.get("mail", user_info.get("userPrincipalName", "")),
        "name": user_info.get("displayName", ""),
        "is_admin": is_admin,
    }

    next_url = request.session.pop("auth_next", "/sender/")
    return RedirectResponse(url=next_url)


@app.get("/auth/logout")
async def auth_logout(request: Request):
    """ログアウト"""
    request.session.clear()
    return RedirectResponse(url="/")


@app.get("/")
async def root():
    """ルートリダイレクト"""
    return RedirectResponse(url="/sender/")


@app.on_event("startup")
async def startup():
    """アプリケーション起動時の処理"""
    logger.info("Starting %s", settings.app_name)
    # ストレージディレクトリの作成
    storage_path = Path(settings.storage_path)
    storage_path.mkdir(parents=True, exist_ok=True)


@app.on_event("shutdown")
async def shutdown():
    """アプリケーション終了時の処理"""
    logger.info("Shutting down %s", settings.app_name)
