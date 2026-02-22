"""ファイル暗号化・保管・削除サービス

Azure Blob Storage またはローカルディスクにファイルを暗号化保存する。
storage_backend 設定で切り替え可能。
"""

import logging
import os
import uuid
from pathlib import Path

import aiofiles
from cryptography.fernet import Fernet

from app.config import settings

logger = logging.getLogger(__name__)


class FileManager:
    """ファイルの暗号化保管と復号を管理"""

    def __init__(self) -> None:
        if not settings.encryption_key:
            raise ValueError("ENCRYPTION_KEY is not configured")
        self.fernet = Fernet(settings.encryption_key.encode())
        self.backend = settings.storage_backend

        if self.backend == "azure_blob":
            self._init_blob_storage()
        else:
            self.storage_path = Path(settings.storage_path)
            self.storage_path.mkdir(parents=True, exist_ok=True)

    def _init_blob_storage(self) -> None:
        """Azure Blob Storage クライアントを初期化"""
        from azure.storage.blob.aio import ContainerClient

        if not settings.azure_storage_connection_string:
            raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not configured")
        self._container_client = ContainerClient.from_connection_string(
            settings.azure_storage_connection_string,
            container_name=settings.azure_storage_container_name,
        )

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

        if self.backend == "azure_blob":
            await self._store_blob(stored_filename, encrypted_data)
        else:
            await self._store_local(stored_filename, encrypted_data)

        return stored_filename, file_size

    async def retrieve_file(self, stored_filename: str) -> bytes:
        """暗号化ファイルを復号して返す"""
        if self.backend == "azure_blob":
            encrypted_data = await self._retrieve_blob(stored_filename)
        else:
            encrypted_data = await self._retrieve_local(stored_filename)

        return self.fernet.decrypt(encrypted_data)

    async def delete_file(self, stored_filename: str) -> bool:
        """保管ファイルを削除する"""
        if self.backend == "azure_blob":
            return await self._delete_blob(stored_filename)
        else:
            return await self._delete_local(stored_filename)

    def get_storage_usage_mb(self) -> float:
        """ストレージ使用量をMBで返す（ローカルバックエンドのみ対応）"""
        if self.backend == "azure_blob":
            return 0.0
        total = sum(
            f.stat().st_size
            for f in Path(settings.storage_path).rglob("*")
            if f.is_file()
        )
        return total / (1024 * 1024)

    # --- Azure Blob Storage バックエンド ---

    async def _store_blob(self, blob_name: str, data: bytes) -> None:
        """Azure Blob Storage にファイルをアップロード"""
        async with self._container_client:
            blob_client = self._container_client.get_blob_client(blob_name)
            await blob_client.upload_blob(data, overwrite=True)
        self._init_blob_storage()
        logger.debug("Stored blob: %s", blob_name)

    async def _retrieve_blob(self, blob_name: str) -> bytes:
        """Azure Blob Storage からファイルをダウンロード"""
        async with self._container_client:
            blob_client = self._container_client.get_blob_client(blob_name)
            stream = await blob_client.download_blob()
            data = await stream.readall()
        self._init_blob_storage()
        return data

    async def _delete_blob(self, blob_name: str) -> bool:
        """Azure Blob Storage からファイルを削除"""
        try:
            async with self._container_client:
                blob_client = self._container_client.get_blob_client(blob_name)
                await blob_client.delete_blob()
            self._init_blob_storage()
            return True
        except Exception:
            logger.warning("Failed to delete blob: %s", blob_name)
            self._init_blob_storage()
            return False

    async def list_blobs(self) -> list[str]:
        """Azure Blob Storage のファイル一覧を取得"""
        blob_names: list[str] = []
        async with self._container_client:
            async for blob in self._container_client.list_blobs():
                blob_names.append(blob.name)
        self._init_blob_storage()
        return blob_names

    # --- ローカルディスクバックエンド ---

    async def _store_local(self, stored_filename: str, data: bytes) -> None:
        """ローカルディスクにファイルを保存"""
        file_path = self.storage_path / stored_filename
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(data)

    async def _retrieve_local(self, stored_filename: str) -> bytes:
        """ローカルディスクからファイルを読み取り"""
        file_path = self.storage_path / stored_filename
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {stored_filename}")
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    async def _delete_local(self, stored_filename: str) -> bool:
        """ローカルディスクからファイルを削除"""
        file_path = self.storage_path / stored_filename
        if file_path.exists():
            os.remove(file_path)
            return True
        return False
