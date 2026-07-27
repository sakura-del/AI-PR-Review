"""llm_token_usage_total 指标测试（T22 [A18]）

覆盖：
- 成功响应提取 prompt/completion tokens 并写入 Counter
- 不同 model 分别累计
- prompt vs completion 分别计数
- 无 usage 字段的响应静默跳过
- usage 字段为 None / 字段缺失
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_pr_review.core.analyzer import AIAnalyzer, _record_token_usage
from ai_pr_review.core.config import AppConfig
from ai_pr_review.core.metrics import get_registry


@pytest.fixture(autouse=True)
def reset_registry():
    get_registry().reset()
    yield
    get_registry().reset()


def _make_config(model: str = "deepseek-chat") -> AppConfig:
    return AppConfig(
        ai=AppConfig.__dataclass_fields__["ai"].default_factory(),
        github=AppConfig.__dataclass_fields__["github"].default_factory(),
        analysis=AppConfig.__dataclass_fields__["analysis"].default_factory(),
        expert=AppConfig.__dataclass_fields__["expert"].default_factory(),
    )


def _make_response(prompt_tokens=None, completion_tokens=None, has_usage=True):
    """构造带 usage 字段的 mock response"""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "{}"
    if has_usage:
        usage = MagicMock()
        usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens
        response.usage = usage
    else:
        response.usage = None
    return response


def test_record_token_usage_basic():
    """基础提取：prompt_tokens=100, completion_tokens=50"""
    response = _make_response(prompt_tokens=100, completion_tokens=50)

    _record_token_usage(response, model="deepseek-chat")

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    assert counter.get(model="deepseek-chat", type="prompt") == 100
    assert counter.get(model="deepseek-chat", type="completion") == 50


def test_record_token_usage_separates_models():
    """不同 model 各自累计"""
    _record_token_usage(_make_response(100, 50), model="deepseek-chat")
    _record_token_usage(_make_response(200, 80), model="qwen-plus")

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    assert counter.get(model="deepseek-chat", type="prompt") == 100
    assert counter.get(model="deepseek-chat", type="completion") == 50
    assert counter.get(model="qwen-plus", type="prompt") == 200
    assert counter.get(model="qwen-plus", type="completion") == 80


def test_record_token_usage_accumulates_across_calls():
    """多次调用应累计（Counter 单调递增）"""
    _record_token_usage(_make_response(100, 50), model="deepseek-chat")
    _record_token_usage(_make_response(200, 100), model="deepseek-chat")
    _record_token_usage(_make_response(50, 25), model="deepseek-chat")

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    assert counter.get(model="deepseek-chat", type="prompt") == 350  # 100+200+50
    assert counter.get(model="deepseek-chat", type="completion") == 175  # 50+100+25


def test_record_token_usage_no_usage_field_skipped():
    """usage 字段为 None 时静默跳过，不抛异常"""
    response = _make_response(has_usage=False)
    _record_token_usage(response, model="deepseek-chat")  # 不应抛

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    # 不应创建该 counter 的任何条目（或创建了但全为 0）
    snapshot = counter.snapshot()
    assert snapshot == []


def test_record_token_usage_missing_fields_skipped():
    """usage 存在但 prompt_tokens 为 None 时只记录 completion"""
    response = MagicMock()
    response.usage = MagicMock()
    response.usage.prompt_tokens = None
    response.usage.completion_tokens = 75

    _record_token_usage(response, model="qwen-plus")

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    # prompt 没被记录，completion 是 75
    assert counter.get(model="qwen-plus", type="completion") == 75
    # prompt entry 不存在
    snapshot = counter.snapshot()
    assert len(snapshot) == 1


def test_record_token_usage_handles_non_numeric_gracefully():
    """usage.prompt_tokens 为非数字时跳过（不抛异常）"""
    response = MagicMock()
    response.usage = MagicMock()
    response.usage.prompt_tokens = "invalid"  # type: ignore
    response.usage.completion_tokens = 50

    _record_token_usage(response, model="glm-4")  # 不应抛

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    # 只有 completion 被记录
    assert counter.get(model="glm-4", type="completion") == 50


# ===== 集成测试：_call_ai 成功路径应自动提取 =====

@pytest.mark.asyncio
async def test_call_ai_records_token_usage_on_success():
    """成功调用 _call_ai 后应自动提取 token 用量"""
    config = _make_config()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"summary": {}, "findings": [], "suggestions": []}'
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 1500
    mock_response.usage.completion_tokens = 300

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("ai_pr_review.core.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)
        await analyzer._call_ai([{"role": "user", "content": "hi"}])

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    assert counter.get(model="deepseek-chat", type="prompt") == 1500
    assert counter.get(model="deepseek-chat", type="completion") == 300


@pytest.mark.asyncio
async def test_call_ai_records_token_usage_for_custom_model():
    """自定义 model 名也能正确累计"""
    config = _make_config()
    config.ai.model = "qwen-plus"  # 覆盖默认

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"summary": {}, "findings": [], "suggestions": []}'
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 2000
    mock_response.usage.completion_tokens = 500

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("ai_pr_review.core.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)
        await analyzer._call_ai([{"role": "user", "content": "hi"}])

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    # 应该在 qwen-plus 名下记录
    assert counter.get(model="qwen-plus", type="prompt") == 2000
    assert counter.get(model="qwen-plus", type="completion") == 500
    # 不应在 deepseek-chat 名下
    assert counter.get(model="deepseek-chat", type="prompt") == 0


@pytest.mark.asyncio
async def test_call_ai_does_not_record_token_usage_on_failure():
    """失败路径不写 token（因为没收到 usage）"""
    config = _make_config()
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("api down"))

    with patch("ai_pr_review.core.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)
        with patch("ai_pr_review.core.analyzer.asyncio.sleep", new=AsyncMock()):
            await analyzer._call_ai([{"role": "user", "content": "hi"}])

    counter = get_registry().counter("llm_token_usage_total", labels=("model", "type"))
    snapshot = counter.snapshot()
    assert snapshot == []  # 失败时无 token 记录