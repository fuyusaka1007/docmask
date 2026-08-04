"""操作日志配置模块"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from docmask.config import LOG_FILE, DEFAULT_LOG_LEVEL


def setup_logging(
    level: str = DEFAULT_LOG_LEVEL,
    log_file: str | None = LOG_FILE,
    console: bool = True,
) -> None:
    """
    配置日志系统
    - 日志中只记录操作元数据（时间、文件、替换次数），不记录具体替换内容
    - 同时输出到文件和控制台
    - 日志目录自动创建在平台用户数据目录下
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handler
    root_logger.handlers.clear()

    # 文件 handler：确保日志目录存在
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
            root_logger.addHandler(file_handler)
        except OSError:
            pass

    # 控制台 handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
        root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """获取模块日志器"""
    return logging.getLogger(name)