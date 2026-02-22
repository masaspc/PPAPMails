"""FileManagerサービスのテスト"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.file_manager import FileManager


@pytest.fixture
def temp_storage(tmp_path):
    """テスト用一時ストレージ"""
    storage_dir = tmp_path / "files"
    storage_dir.mkdir()
    return str(storage_dir)


@pytest.fixture
def file_manager(temp_storage):
    """テスト用FileManagerインスタンス"""
    with patch("app.services.file_manager.settings") as mock_settings:
        mock_settings.storage_path = temp_storage
        mock_settings.encryption_key = "ZHVtbXktdGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Ng=="
        mock_settings.max_file_size_mb = 50
        # Fernet鍵を生成して使用
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        mock_settings.encryption_key = key
        fm = FileManager()
        yield fm


@pytest.mark.asyncio
async def test_store_and_retrieve_file(file_manager):
    """ファイルの保存と取得が正しく動作するか"""
    original_data = b"Hello, this is a test file content."
    stored_filename, file_size = await file_manager.store_file(original_data, "test.txt")

    assert file_size == len(original_data)
    assert stored_filename.endswith("_test.txt.enc")

    retrieved_data = await file_manager.retrieve_file(stored_filename)
    assert retrieved_data == original_data


@pytest.mark.asyncio
async def test_delete_file(file_manager):
    """ファイル削除が正しく動作するか"""
    original_data = b"File to delete"
    stored_filename, _ = await file_manager.store_file(original_data, "delete_me.txt")

    result = await file_manager.delete_file(stored_filename)
    assert result is True

    # 再度削除しても False
    result = await file_manager.delete_file(stored_filename)
    assert result is False


@pytest.mark.asyncio
async def test_file_size_limit(file_manager):
    """ファイルサイズ制限が機能するか"""
    with patch.object(file_manager, "fernet"):
        from app.config import settings
        with patch("app.services.file_manager.settings") as mock_settings:
            mock_settings.max_file_size_mb = 1  # 1MB制限
            mock_settings.storage_path = file_manager.storage_path
            mock_settings.encryption_key = "test"

            # 元のfile_managerのmax_file_size_mbを変更
            large_data = b"x" * (2 * 1024 * 1024)  # 2MB
            with pytest.raises(ValueError, match="exceeds maximum"):
                await file_manager.store_file(large_data, "large.bin")


@pytest.mark.asyncio
async def test_retrieve_nonexistent_file(file_manager):
    """存在しないファイルの取得でエラーが出るか"""
    with pytest.raises(FileNotFoundError):
        await file_manager.retrieve_file("nonexistent_file.enc")


def test_storage_usage(file_manager, temp_storage):
    """ストレージ使用量の計算"""
    # 空のディレクトリ
    usage = file_manager.get_storage_usage_mb()
    assert usage == 0.0
