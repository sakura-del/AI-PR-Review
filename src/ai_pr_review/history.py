import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

HISTORY_DIR = Path.home() / ".ai-pr-review" / "history"
MAX_RECORDS = 100


@dataclass
class AnalysisRecord:
    pr_url: str
    pr_title: str
    timestamp: str = ""
    findings_count: int = 0
    high_severity_count: int = 0
    medium_severity_count: int = 0
    low_severity_count: int = 0
    suggestions_count: int = 0
    model: str = ""
    duration_seconds: float = 0.0
    head_sha: str = ""
    base_sha: str = ""
    is_incremental: bool = False

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def save_record(record: AnalysisRecord) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    record_file = HISTORY_DIR / f"{record.timestamp.replace(':', '-')}.json"
    
    records = load_records()
    records.insert(0, record)
    if len(records) > MAX_RECORDS:
        records = records[:MAX_RECORDS]
    
    all_data = [asdict(r) for r in records]
    with open(HISTORY_DIR / "history.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)


def load_records() -> list[AnalysisRecord]:
    history_file = HISTORY_DIR / "history.json"
    if not history_file.exists():
        return []
    
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [_parse_record(item) for item in data]
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to load history: {e}")
        return []


def _parse_record(item: dict) -> AnalysisRecord:
    known_fields = {f.name for f in AnalysisRecord.__dataclass_fields__.values()}
    filtered = {k: v for k, v in item.items() if k in known_fields}
    return AnalysisRecord(**filtered)


def find_last_record(pr_url: str) -> AnalysisRecord | None:
    records = load_records()
    for r in records:
        if r.pr_url == pr_url and r.head_sha:
            return r
    return None


def format_history_table(records: list[AnalysisRecord], limit: int = 20) -> str:
    from rich.table import Table
    from rich.console import Console
    
    console = Console()
    table = Table(title=f"📜 AI PR Review History (showing {min(limit, len(records))} of {len(records)})")
    table.add_column("Time", style="dim", width=20)
    table.add_column("PR", style="cyan")
    table.add_column("Findings", justify="right")
    table.add_column("🔴 H", justify="right")
    table.add_column("🟡 M", justify="right")
    table.add_column("🟢 L", justify="right")
    table.add_column("💡 Sugg", justify="right")
    
    for r in records[:limit]:
        time_str = r.timestamp[:19].replace("T", " ")
        pr_short = r.pr_title[:40] + ("..." if len(r.pr_title) > 40 else "")
        table.add_row(
            time_str,
            pr_short,
            str(r.findings_count),
            str(r.high_severity_count),
            str(r.medium_severity_count),
            str(r.low_severity_count),
            str(r.suggestions_count),
        )
    
    console.print(table)
    return ""
