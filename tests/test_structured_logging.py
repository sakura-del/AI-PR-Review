"""结构化日志 setup_logging 单元测试

覆盖场景：
1. text 格式输出包含 [LEVEL] 前缀
2. json 格式输出可被 json.loads 解析，含 timestamp/level/logger/message 四字段
3. json 输出的 timestamp 符合 ISO8601 格式（含时区）
4. 环境变量 LOG_FORMAT=json 时，不传参调用 setup_logging 输出为 json
5. 连续调用 setup_logging 两次，每条日志只出现一次（无重复 handlers）
6. json 输出中换行符被转义，整体为单行
"""
import io
import json
import logging
from datetime import datetime

import pytest

from ai_pr_review.structured_logging import setup_logging


@pytest.fixture
def clean_root_logger():
    """清理 root logger 的 handlers 与 level，确保测试间隔离"""
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    root.handlers = []
    yield root
    # 恢复原始状态，避免影响后续测试
    root.handlers = old_handlers
    root.setLevel(old_level)


def _capture_output(logger: logging.Logger) -> io.StringIO:
    """将 setup_logging 添加的 handler stream 重定向到 StringIO，便于断言格式化输出"""
    stream = io.StringIO()
    assert len(logger.handlers) == 1, "setup_logging 应仅添加一个 handler"
    logger.handlers[0].stream = stream
    return stream


def test_setup_logging_text_format(clean_root_logger, monkeypatch):
    """text 格式输出包含 [LEVEL] 前缀"""
    # 确保环境变量不干扰
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    logger = setup_logging("text", "INFO")
    stream = _capture_output(logger)

    logger.info("hello world")
    output = stream.getvalue()

    assert "[INFO]" in output
    assert "hello world" in output


def test_setup_logging_json_format_parses(clean_root_logger, monkeypatch):
    """json 格式输出可被 json.loads 解析，含 timestamp/level/logger/message 四字段"""
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    logger = setup_logging("json", "INFO")
    stream = _capture_output(logger)

    logger.info("test message")
    output = stream.getvalue().strip()

    # 必须能被 json.loads 解析
    data = json.loads(output)
    assert "timestamp" in data
    assert "level" in data
    assert "logger" in data
    assert "message" in data
    assert data["level"] == "INFO"
    assert data["message"] == "test message"


def test_setup_logging_json_timestamp_iso8601(clean_root_logger, monkeypatch):
    """json 输出的 timestamp 符合 ISO8601 格式（含时区）"""
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    logger = setup_logging("json", "INFO")
    stream = _capture_output(logger)

    logger.info("ts test")
    output = stream.getvalue().strip()
    data = json.loads(output)
    ts = data["timestamp"]

    # ISO8601 带时区：应能被 datetime.fromisoformat 解析，且 tzinfo 不为 None
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None, "timestamp 应包含时区信息"


def test_setup_logging_env_variable(clean_root_logger, monkeypatch):
    """设置 LOG_FORMAT=json 环境变量，不传参调用 setup_logging 输出为 json"""
    monkeypatch.setenv("LOG_FORMAT", "json")
    logger = setup_logging()  # 不传参，应 fallback 到环境变量
    stream = _capture_output(logger)

    logger.info("env test")
    output = stream.getvalue().strip()

    # 应为合法 json
    data = json.loads(output)
    assert data["message"] == "env test"


def test_setup_logging_repeated_call_no_duplicate(clean_root_logger, monkeypatch):
    """连续调用 setup_logging 两次，每条日志只出现一次（无重复 handlers）"""
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    logger = setup_logging("text", "INFO")
    stream1 = _capture_output(logger)

    # 第二次调用：应清除第一个 handler，避免重复输出
    logger = setup_logging("text", "INFO")
    stream2 = _capture_output(logger)

    logger.info("once")

    # 新 stream 应有内容
    assert "once" in stream2.getvalue()
    # 旧 stream 应无内容（handler 已被移除，不再写入）
    assert "once" not in stream1.getvalue()
    # root logger 仅剩一个 handler
    assert len(logger.handlers) == 1


def test_setup_logging_json_escapes_newlines(clean_root_logger, monkeypatch):
    """json 输出中换行符被转义，整体为单行"""
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    logger = setup_logging("json", "INFO")
    stream = _capture_output(logger)

    logger.info("line1\nline2")
    output = stream.getvalue()

    # 整体应为单行（strip 后无实际换行符）
    assert "\n" not in output.strip(), "json 输出应为单行，换行符应被转义"
    # 可被 json.loads 解析，且 message 内容保留原始换行
    data = json.loads(output.strip())
    assert data["message"] == "line1\nline2"
