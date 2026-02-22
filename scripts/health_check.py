#!/usr/bin/env python3
"""cron: 相互ヘルスチェックスクリプト

各VPSが相手のVPSのヘルスチェックを行い、異常検知時にTeams通知する。

crontab設定例:
  * * * * * /opt/secure-download/venv/bin/python /opt/secure-download/scripts/health_check.py
"""

import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PEER_HEALTH_URL = os.environ.get("PEER_HEALTH_URL", "")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL", "")
HOSTNAME = os.environ.get("HOSTNAME", "unknown")


def check_peer_health() -> dict | None:
    """相手のVPSのヘルスチェックを実行"""
    if not PEER_HEALTH_URL:
        logger.warning("PEER_HEALTH_URL is not configured")
        return None

    try:
        req = urllib.request.Request(PEER_HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error("Peer health check failed: %s", e)
        return None


def send_teams_alert(message: str) -> None:
    """Microsoft Teams にアラートを送信"""
    if not TEAMS_WEBHOOK_URL:
        logger.warning("TEAMS_WEBHOOK_URL is not configured, skipping alert")
        return

    payload = json.dumps({
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "Secure Download Alert",
                        "weight": "bolder",
                        "size": "medium",
                        "color": "attention",
                    },
                    {
                        "type": "TextBlock",
                        "text": message,
                        "wrap": True,
                    },
                    {
                        "type": "TextBlock",
                        "text": f"Source: {HOSTNAME}",
                        "size": "small",
                        "color": "light",
                    },
                ],
            },
        }],
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            TEAMS_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            logger.info("Teams alert sent successfully")
    except Exception:
        logger.exception("Failed to send Teams alert")


def check_local_health() -> dict:
    """自身のヘルスチェック"""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/internal/health", method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main() -> None:
    # ローカルヘルスチェック
    local_health = check_local_health()
    if local_health.get("status") != "ok":
        send_teams_alert(
            f"Local health check failed on {HOSTNAME}: {json.dumps(local_health)}"
        )

    # ピアヘルスチェック
    peer_health = check_peer_health()
    if peer_health is None:
        send_teams_alert(f"Peer VPS is unreachable from {HOSTNAME}")
    elif peer_health.get("status") != "ok":
        send_teams_alert(
            f"Peer VPS health check failed (from {HOSTNAME}): {json.dumps(peer_health)}"
        )


if __name__ == "__main__":
    main()
