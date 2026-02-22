"""Azure Functions: メール処理（Graph APIポーリング）

Exchange Onlineのメールフロールールで処理用メールボックスに転送された
添付ファイル付きメールを Graph API 経由で取得し、処理する。

Timer Trigger で定期実行（デフォルト30秒間隔）。
"""

import asyncio
import base64
import json
import logging
import os
import sys
from pathlib import Path

import azure.functions as func

# アプリケーションモジュールをインポート可能にする
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

bp = func.Blueprint()


@bp.timer_trigger(
    schedule="*/30 * * * * *",
    arg_name="timer",
    run_on_startup=False,
)
async def process_email_timer(timer: func.TimerRequest) -> None:
    """処理用メールボックスをポーリングし、未読メールを処理する"""
    logger.info("Email processing timer triggered")

    try:
        await _poll_and_process_emails()
    except Exception:
        logger.exception("Email processing failed")


async def _poll_and_process_emails() -> None:
    """Graph API で処理用メールボックスの未読メールを取得・処理"""
    from app.config import settings
    from app.database import async_session
    from app.services.email_processor import EmailProcessor
    from app.services.graph_api import GraphAPIClient

    graph_client = GraphAPIClient()
    processing_mailbox = settings.processing_mailbox

    if not processing_mailbox:
        logger.warning("PROCESSING_MAILBOX is not configured, skipping")
        return

    token = await graph_client._get_access_token()

    # 未読の添付ファイル付きメールを取得
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://graph.microsoft.com/v1.0/users/{processing_mailbox}/messages",
            params={
                "$filter": "isRead eq false and hasAttachments eq true",
                "$select": "id,subject,from,toRecipients,ccRecipients,bccRecipients,"
                           "body,hasAttachments,internetMessageId",
                "$top": "50",
                "$orderby": "receivedDateTime asc",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    if response.status_code != 200:
        logger.error("Failed to fetch messages: %d %s", response.status_code, response.text)
        return

    messages = response.json().get("value", [])
    if not messages:
        logger.debug("No unread messages with attachments")
        return

    logger.info("Found %d unread messages to process", len(messages))

    for message in messages:
        try:
            await _process_single_message(message, processing_mailbox, token)
        except Exception:
            logger.exception("Failed to process message %s", message.get("id"))


async def _process_single_message(
    message: dict, mailbox: str, token: str
) -> None:
    """1通のメールを処理する"""
    import email
    import email.mime.multipart
    import email.mime.text
    import email.mime.base
    from email.utils import formataddr

    import httpx

    from app.config import settings
    from app.database import async_session
    from app.services.email_processor import EmailProcessor

    message_id = message["id"]
    logger.info("Processing message: %s (subject: %s)", message_id, message.get("subject", ""))

    # 添付ファイルを取得
    async with httpx.AsyncClient() as client:
        att_response = await client.get(
            f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{message_id}/attachments",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    if att_response.status_code != 200:
        logger.error("Failed to fetch attachments: %d", att_response.status_code)
        return

    attachments = att_response.json().get("value", [])

    # Graph API のメッセージデータから RFC822 形式のメールを再構築
    msg = email.mime.multipart.MIMEMultipart("mixed")

    from_addr = message.get("from", {}).get("emailAddress", {})
    msg["From"] = formataddr((from_addr.get("name", ""), from_addr.get("address", "")))
    msg["Subject"] = message.get("subject", "")
    msg["Message-ID"] = message.get("internetMessageId", f"<{message_id}@graph>")

    to_addrs = [
        r["emailAddress"]["address"]
        for r in message.get("toRecipients", [])
    ]
    cc_addrs = [
        r["emailAddress"]["address"]
        for r in message.get("ccRecipients", [])
    ]
    bcc_addrs = [
        r["emailAddress"]["address"]
        for r in message.get("bccRecipients", [])
    ]

    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)

    # 本文
    body = message.get("body", {})
    body_content = body.get("content", "")
    body_type = body.get("contentType", "text")
    if body_type == "html":
        text_part = email.mime.text.MIMEText(body_content, "html", "utf-8")
    else:
        text_part = email.mime.text.MIMEText(body_content, "plain", "utf-8")
    msg.attach(text_part)

    # 添付ファイル
    for att in attachments:
        if att.get("@odata.type") == "#microsoft.graph.fileAttachment":
            content_bytes = base64.b64decode(att.get("contentBytes", ""))
            mime_part = email.mime.base.MIMEBase("application", "octet-stream")
            mime_part.set_payload(content_bytes)
            email.encoders.encode_base64(mime_part)
            mime_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=att.get("name", "file"),
            )
            msg.attach(mime_part)

    # EmailProcessor で処理
    raw_data = msg.as_bytes()
    async with async_session() as db:
        processor = EmailProcessor(db)
        transfer_id = await processor.process_email_bytes(raw_data)
        await db.commit()
        logger.info("Processed message %s -> transfer %s", message_id, transfer_id)

    # 処理済みメールを既読にする
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{message_id}",
            json={"isRead": True},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
