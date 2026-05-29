import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ai_pr_review.models import (
    ParsedDiff,
    FileDiff,
    DiffHunk,
    ChangeType,
    PRMetadata,
)
from ai_pr_review.analyzer import AIAnalyzer
from ai_pr_review.config import AppConfig


def _make_config() -> AppConfig:
    return AppConfig(
        ai=AppConfig.__dataclass_fields__["ai"].default_factory(),
        github=AppConfig.__dataclass_fields__["github"].default_factory(),
        analysis=AppConfig.__dataclass_fields__["analysis"].default_factory(),
        expert=AppConfig.__dataclass_fields__["expert"].default_factory(),
    )


def _make_metadata() -> PRMetadata:
    return PRMetadata(
        title="Test PR",
        description="Test description",
        author="testuser",
        base_branch="main",
        head_branch="feature",
        labels=[],
        url="https://github.com/test/repo/pull/1",
        number=1,
        repo_owner="test",
        repo_name="repo",
    )


def _make_small_diff() -> ParsedDiff:
    hunk = DiffHunk(
        file_path="test.py",
        change_type=ChangeType.MODIFIED,
        old_start=1, old_count=5,
        new_start=1, new_count=10,
        content="@@ -1 +5 @@\n+new line\n-old line",
        header="@@ -1 +5 @@",
    )
    f = FileDiff(
        path="test.py",
        change_type=ChangeType.MODIFIED,
        hunks=[hunk],
        additions=10,
        deletions=5,
    )
    return ParsedDiff(files=[f], total_additions=10, total_deletions=5)


async def _mock_stream_response(items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_stream_yields_content():
    config = _make_config()
    metadata = _make_metadata()
    diff = _make_small_diff()

    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "streamed content"

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_mock_stream_response([mock_chunk]))

    with patch("ai_pr_review.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)

        chunks = []
        async for chunk in analyzer.analyze_stream(metadata, diff):
            chunks.append(chunk)

        assert len(chunks) > 0
        assert "streamed content" in "".join(chunks)


@pytest.mark.asyncio
async def test_stream_handles_error():
    config = _make_config()
    metadata = _make_metadata()
    diff = _make_small_diff()

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

    with patch("ai_pr_review.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)

        chunks = []
        async for chunk in analyzer.analyze_stream(metadata, diff):
            chunks.append(chunk)

        assert "" in chunks


@pytest.mark.asyncio
async def test_stream_empty_response():
    config = _make_config()
    metadata = _make_metadata()
    diff = _make_small_diff()

    mock_chunk_empty = MagicMock()
    mock_chunk_empty.choices = []

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_mock_stream_response([mock_chunk_empty]))

    with patch("ai_pr_review.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)

        chunks = []
        async for chunk in analyzer.analyze_stream(metadata, diff):
            chunks.append(chunk)

        assert len(chunks) == 0 or all(c == "" for c in chunks if c is not None)


@pytest.mark.asyncio
async def test_stream_multiple_chunks():
    config = _make_config()
    metadata = _make_metadata()
    diff = _make_small_diff()

    chunks_data = ["chunk1", "chunk2", "chunk3"]
    mock_chunks = []
    for data in chunks_data:
        mc = MagicMock()
        mc.choices = [MagicMock()]
        mc.choices[0].delta.content = data
        mock_chunks.append(mc)

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_mock_stream_response(mock_chunks))

    with patch("ai_pr_review.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)

        collected = []
        async for chunk in analyzer.analyze_stream(metadata, diff):
            collected.append(chunk)

        result = "".join(collected)
        assert result == "chunk1chunk2chunk3"


@pytest.mark.asyncio
async def test_stream_applies_filters():
    config = _make_config()
    metadata = _make_metadata()
    diff = _make_small_diff()

    json_response = '{"summary":{"intent":"test","scope":"small","key_changes":[]},"findings":[{"type":"bug","severity":"low","confidence":2,"expert":"security","file":"x.py","line":1,"title":"Low confidence","description":"","suggestion":"","code_snippet":""}],"suggestions":[]}'

    mock_chunks = [MagicMock() for _ in range(2)]
    for i, mc in enumerate(mock_chunks):
        mc.choices = [MagicMock()]
        mc.choices[0].delta.content = json_response[:len(json_response)//2] if i == 0 else json_response[len(json_response)//2:]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_mock_stream_response(mock_chunks))

    with patch("ai_pr_review.analyzer.AsyncOpenAI", return_value=mock_client):
        analyzer = AIAnalyzer(config=config)

        collected = []
        async for chunk in analyzer.analyze_stream(metadata, diff, severity_threshold="medium"):
            collected.append(chunk)
