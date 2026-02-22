"""ファイル暗号化・保管・削除サービス"""

import os
import uuid
from pathlib import Path

import aiofiles
from cryptography.fernet import Fernet

from app.config import settings


class FileManager:
    """ファイルの暗号化保管と復号を管理"""

    def __init__(self) -> None:
        if not settings.encryption_key:
            raise ValueError("ENCRYPTION_KEY is not configured")
        self.fernet = Fernet(settings.encryption_key.encode())
        self.storage_path = Path(settings.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, stored_filename: str) -> Path:
        return self.storage_path / stored_filename

    async def store_file(self, file_data: bytes, original_filename: str) -> tuple[str, int]:
        """ファイルを暗号化して保管する

        Returns:
            tuple[str, int]: (保管ファイル名, 元ファイルサイズ)
        """
        file_size = len(file_data)
        max_size = settings.max_file_size_mb * 1024 * 1024
        if file_size > max_size:
            raise ValueError(
                f"File size {file_size} exceeds maximum {settings.max_file_size_mb}MB"
            )

        encrypted_data = self.fernet.encrypt(file_data)
        stored_filename = f"{uuid.uuid4().hex}_{original_filename}.enc"
        file_path = self._get_file_path(stored_filename)

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(encrypted_data)

        return stored_filename, file_size

    async def retrieve_file(self, stored_filename: str) -> bytes:
        """暗号化ファイルを復号して返す"""
        file_path = self._get_file_path(stored_filename)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {stored_filename}")

        async with aiofiles.open(file_path, "rb") as f:
            encrypted_data = await f.read()

        return self.fernet.decrypt(encrypted_data)

    async def delete_file(self, stored_filename: str) -> bool:
        """保管ファイルを削除する"""
        file_path = self._get_file_path(stored_filename)
        if file_path.exists():
            os.remove(file_path)
            return True
        return False

    def get_storage_usage_mb(self) -> float:
        """ストレージ使用量をMBで返す"""
        total = sum(
            f.stat().st_size for f in self.storage_path.rglob("*") if f.is_file()
        )
        return total / (1024 * 1024)
