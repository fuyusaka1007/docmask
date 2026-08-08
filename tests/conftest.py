"""pytest 全局配置：隔离用户数据目录，防止测试污染生产环境。"""
import pytest
from unittest.mock import patch
from pathlib import Path


@pytest.fixture(autouse=True)
def isolate_user_data_dir(tmp_path):
    """将 user_data_dir 指向临时目录，避免测试写入真实用户数据目录。

    覆盖范围：
    - docmask.utils.file_utils.user_data_dir
    - docmask.services.codebook_library.user_data_dir（import 时绑定）
    - docmask.services.history_store.user_data_dir（import 时绑定）
    """
    fake_dir = tmp_path / "user_data"
    fake_dir.mkdir(parents=True, exist_ok=True)

    with patch("docmask.utils.file_utils.user_data_dir", return_value=fake_dir), \
         patch("docmask.services.codebook_library.user_data_dir", return_value=fake_dir), \
         patch("docmask.services.history_store.user_data_dir", return_value=fake_dir):
        yield
