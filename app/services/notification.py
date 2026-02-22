"""メール通知サービス（URL通知・認証コード送信）"""

import logging

from app.config import settings
from app.services.graph_api import GraphAPIClient

logger = logging.getLogger(__name__)


class NotificationService:
    """メール通知の送信を管理"""

    def __init__(self) -> None:
        self.graph_client = GraphAPIClient()
        self.portal_domain = settings.portal_domain

    async def send_auth_code_email(self, to_email: str, code: str) -> bool:
        """認証コードメールを送信"""
        subject = f"【TBN Secure Download】認証コード: {code}"
        body_html = f"""
        <html>
        <body style="font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 32px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h2 style="color: #1a56db; margin-top: 0;">TBN Secure Download</h2>
                <p>ファイルダウンロードの認証コードをお知らせします。</p>
                <div style="background-color: #f0f4ff; border: 2px solid #1a56db; border-radius: 8px; padding: 20px; text-align: center; margin: 24px 0;">
                    <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1a56db;">{code}</span>
                </div>
                <p style="color: #666; font-size: 14px;">
                    このコードは{settings.auth_code_expiry_minutes}分間有効です。<br>
                    心当たりがない場合は、このメールを無視してください。
                </p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
                <p style="color: #999; font-size: 12px;">
                    東京ベイネットワーク株式会社<br>
                    このメールは自動送信です。返信はできません。
                </p>
            </div>
        </body>
        </html>
        """
        return await self.graph_client.send_email(
            to_recipients=[to_email],
            subject=subject,
            body_html=body_html,
        )

    async def send_download_notification(
        self,
        to_recipients: list[str],
        cc_recipients: list[str],
        bcc_recipients: list[str],
        original_subject: str,
        original_body: str,
        sender_email: str,
        download_links: list[dict[str, str]],
    ) -> bool:
        """添付ファイルをURLに置換した再構築メールを送信"""
        links_html = ""
        for link in download_links:
            links_html += f"""
            <tr>
                <td style="padding: 8px 12px; border-bottom: 1px solid #eee;">
                    📎 {link['filename']}
                </td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #eee;">
                    {link['size']}
                </td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #eee;">
                    <a href="https://{self.portal_domain}/d/{link['token']}"
                       style="color: #1a56db; text-decoration: none;">ダウンロード</a>
                </td>
            </tr>
            """

        attachment_section = f"""
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 16px 0;">
            <p style="margin: 0 0 12px 0; font-weight: bold; color: #334155;">
                🔒 セキュアダウンロード
            </p>
            <p style="margin: 0 0 12px 0; color: #64748b; font-size: 14px;">
                添付ファイルはセキュリティ保護のため、以下のリンクからダウンロードしてください。<br>
                ダウンロード時にメールアドレス認証が必要です。
            </p>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background-color: #e2e8f0;">
                        <th style="padding: 8px 12px; text-align: left;">ファイル名</th>
                        <th style="padding: 8px 12px; text-align: left;">サイズ</th>
                        <th style="padding: 8px 12px; text-align: left;"></th>
                    </tr>
                </thead>
                <tbody>
                    {links_html}
                </tbody>
            </table>
            <p style="margin: 12px 0 0 0; color: #94a3b8; font-size: 12px;">
                ※ リンクの有効期限: {settings.download_expiry_days}日間
            </p>
        </div>
        """

        body_html = f"""
        <html>
        <body style="font-family: 'Segoe UI', Arial, sans-serif;">
            <div>{original_body}</div>
            {attachment_section}
            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
            <p style="color: #999; font-size: 11px;">
                このメールは TBN Secure Download により添付ファイルがセキュアダウンロードリンクに変換されています。<br>
                送信元: {sender_email}
            </p>
        </body>
        </html>
        """

        subject = original_subject

        return await self.graph_client.send_email(
            to_recipients=to_recipients,
            subject=subject,
            body_html=body_html,
            cc_recipients=cc_recipients if cc_recipients else None,
            bcc_recipients=bcc_recipients if bcc_recipients else None,
        )
