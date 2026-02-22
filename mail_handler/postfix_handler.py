#!/usr/bin/env python3
"""Postfix transport hookスクリプト

Postfixがメールを受信した際にこのスクリプトが呼ばれ、
stdinから生メールデータを読み取り、内部APIにメール処理をリクエストする。

Postfix設定:
  transport_maps = hash:/etc/postfix/transport
  /etc/postfix/transport:
    *  tbn-handler:

  master.cf に以下を追加:
    tbn-handler unix - n n - 10 pipe
      flags=DRXhu user=tbn-app argv=/opt/tbn-secure-download/mail_handler/postfix_handler.py
"""

import json
import logging
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

INTERNAL_API_URL = os.environ.get(
    "INTERNAL_API_URL", "http://127.0.0.1:8000/internal/process-email"
)
MAIL_SPOOL_DIR = os.environ.get(
    "MAIL_SPOOL_DIR", "/var/tbn-secure-download/mail_spool"
)

logging.basicConfig(
    filename="/var/log/tbn-secure-download/mail_handler.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    """メインエントリポイント"""
    try:
        # stdinから生メールデータを読み取る
        raw_email = sys.stdin.buffer.read()
        if not raw_email:
            logger.error("No email data received from stdin")
            return 1

        # 一時ファイルに保存
        spool_dir = Path(MAIL_SPOOL_DIR)
        spool_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            dir=spool_dir, suffix=".eml", delete=False
        ) as f:
            f.write(raw_email)
            temp_path = f.name

        logger.info("Saved raw email to %s (%d bytes)", temp_path, len(raw_email))

        # 内部APIにリクエスト
        payload = json.dumps({"raw_email_path": temp_path}).encode("utf-8")
        req = urllib.request.Request(
            INTERNAL_API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if result.get("success"):
            logger.info(
                "Email processed successfully: transfer_id=%s",
                result.get("transfer_id"),
            )
            # 処理済みの一時ファイルを削除
            os.unlink(temp_path)
            return 0
        else:
            logger.error("Email processing failed: %s", result.get("message"))
            return 1

    except Exception:
        logger.exception("Unexpected error in mail handler")
        return 1


if __name__ == "__main__":
    sys.exit(main())
