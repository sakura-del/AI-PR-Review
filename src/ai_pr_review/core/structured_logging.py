"""结构化日志配置模块

支持两种格式：
- text: 人类可读的终端格式 `[LEVEL] message`（无 timestamp，便于阅读）
- json: 单行 JSON，含 timestamp/level/logger/message 字段，便于机器解析与采集

通过 setup_logging() 配置根 logger，重复调用会清除既有 handlers 避免重复输出。
格式也可通过环境变量 LOG_FORMAT 切换（调用方未显式传 format 时 fallback 到 env）。
"""
import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """JSON 格式化器：将日志记录拼装为单行 JSON 字符串

    输出字段：timestamp(ISO8601带时区)、level、logger(logger名)、message
    message 中的换行等特殊字符由 json.dumps 自动转义，保证输出始终单行可解析。
    """

    def format(self, record: logging.LogRecord) -> str:
        # ISO8601 带时区的时间戳
        timestamp = datetime.now(timezone.utc).isoformat()
        log_obj = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # ensure_ascii=False 保证中文可读；json.dumps 自动转义换行符等特殊字符
        return json.dumps(log_obj, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """文本格式化器：`[LEVEL] message`，无 timestamp，便于终端阅读"""

    def format(self, record: logging.LogRecord) -> str:
        return f"[{record.levelname}] {record.getMessage()}"


def setup_logging(format: str | None = None, level: str = "INFO") -> logging.Logger:
    """配置根日志记录器，返回配置后的 logger。

    Args:
        format: "text"（人类可读）或 "json"（单行 JSON）；
                未显式传参时 fallback 到环境变量 LOG_FORMAT，最终默认 "text"
        level: "DEBUG"/"INFO"/"WARNING"/"ERROR"/"CRITICAL"

    Returns:
        配置后的根 logger
    """
    # 调用方未显式传 format 时，fallback 到环境变量 LOG_FORMAT，最终默认 "text"
    if format is None:
        format = os.environ.get("LOG_FORMAT", "text")

    # level 字符串转 logging 常量，无效时回退到 INFO
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # 选择 Formatter
    if format == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = TextFormatter()

    # 配置根 logger
    root_logger = logging.getLogger()
    # 清除既有 handlers，避免重复调用时重复输出
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)

    return root_logger
