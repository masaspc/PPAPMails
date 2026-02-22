"""Microsoft Graph API連携サービス"""

import logging

import httpx
import msal

from app.config import settings

logger = logging.getLogger(__name__)


class GraphAPIClient:
    """Microsoft Graph APIを使用したメール送信"""

    def __init__(self) -> None:
        self.app = msal.ConfidentialClientApplication(
            settings.azure_client_id,
            authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
            client_credential=settings.azure_client_secret,
        )
        self._token_cache: dict[str, str] = {}

    async def _get_access_token(self) -> str:
        """Graph APIのアクセストークンを取得（クライアント資格情報フロー）"""
        result = self.app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            error = result.get("error_description", "Unknown error")
            raise RuntimeError(f"Failed to acquire Graph API token: {error}")
        return result["access_token"]

    async def send_email(
        self,
        to_recipients: list[str],
        subject: str,
        body_html: str,
        cc_recipients: list[str] | None = None,
        bcc_recipients: list[str] | None = None,
    ) -> bool:
        """Graph APIでメールを送信

        Args:
            to_recipients: To宛先リスト
            subject: 件名
            body_html: HTML本文
            cc_recipients: CC宛先リスト
            bcc_recipients: BCC宛先リスト

        Returns:
            送信成功したか
        """
        token = await self._get_access_token()

        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": [
                    {"emailAddress": {"address": addr}} for addr in to_recipients
                ],
            },
            "saveToSentItems": "true",
        }

        if cc_recipients:
            message["message"]["ccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in cc_recipients
            ]
        if bcc_recipients:
            message["message"]["bccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in bcc_recipients
            ]

        sender = settings.graph_sender_email
        url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=message,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )

        if response.status_code == 202:
            logger.info("Email sent successfully to %s", to_recipients)
            return True

        logger.error(
            "Failed to send email: %d %s", response.status_code, response.text
        )
        return False
