"""Dashboard — HTML 页面展示审查历史与统计

设计目标：
- 纯字符串模板生成 HTML，避免引入 Jinja2/前端框架
- 复用 history.load_records 作为数据源
- 内联 CSS，单文件可部署
- 统计指标：总数、HIGH/MEDIUM/LOW 分布、平均耗时、增量审查占比
"""
import html
import logging
from typing import Optional

from ai_pr_review.history import AnalysisRecord, load_records

logger = logging.getLogger(__name__)


def _escape(text: str) -> str:
    """HTML 转义，防止 XSS（PR 标题可能含特殊字符）"""
    return html.escape(text or "")


def _truncate(text: str, max_len: int = 60) -> str:
    """截断长文本，避免单元格过宽"""
    if not text:
        return ""
    return text[:max_len] + "..." if len(text) > max_len else text


def compute_stats(records: list[AnalysisRecord]) -> dict:
    """计算统计指标"""
    if not records:
        return {
            "total": 0,
            "high": 0, "medium": 0, "low": 0,
            "avg_duration": 0.0,
            "incremental_count": 0,
            "incremental_ratio": 0.0,
        }
    total = len(records)
    high = sum(r.high_severity_count for r in records)
    medium = sum(r.medium_severity_count for r in records)
    low = sum(r.low_severity_count for r in records)
    avg_duration = sum(r.duration_seconds for r in records) / total
    inc_count = sum(1 for r in records if r.is_incremental)
    return {
        "total": total,
        "high": high,
        "medium": medium,
        "low": low,
        "avg_duration": round(avg_duration, 2),
        "incremental_count": inc_count,
        "incremental_ratio": round(inc_count / total, 2),
    }


def _render_stat_cards(stats: dict) -> str:
    """渲染顶部统计卡片"""
    cards = [
        ("总审查数", stats["total"], "#3b82f6"),
        ("HIGH 发现", stats["high"], "#ef4444"),
        ("MEDIUM 发现", stats["medium"], "#f59e0b"),
        ("LOW 发现", stats["low"], "#10b981"),
        ("平均耗时(s)", stats["avg_duration"], "#8b5cf6"),
        ("增量审查占比", f"{stats['incremental_ratio'] * 100:.0f}%", "#06b6d4"),
    ]
    parts = ['<div class="stats-grid">']
    for label, value, color in cards:
        parts.append(
            f'<div class="stat-card" style="border-left: 4px solid {color};">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value" style="color: {color};">{value}</div>'
            f'</div>'
        )
    parts.append('</div>')
    return "\n".join(parts)


def _render_table(records: list[AnalysisRecord]) -> str:
    """渲染历史记录表格"""
    if not records:
        return '<p class="empty">暂无审查记录</p>'

    parts = ['<table class="history-table">']
    parts.append(
        "<thead><tr>"
        "<th>时间</th><th>PR 标题</th><th>发现</th>"
        "<th>HIGH</th><th>MEDIUM</th><th>LOW</th>"
        "<th>耗时(s)</th><th>增量</th><th>模型</th>"
        "</tr></thead><tbody>"
    )
    for r in records:
        title_link = f'<a href="{_escape(r.pr_url)}" target="_blank">{_escape(_truncate(r.pr_title))}</a>'
        inc_badge = '<span class="badge badge-info">增量</span>' if r.is_incremental else '<span class="badge">-</span>'
        parts.append(
            "<tr>"
            f'<td class="time">{_escape(r.timestamp[:19])}</td>'
            f'<td class="title">{title_link}</td>'
            f'<td class="num">{r.findings_count}</td>'
            f'<td class="num high">{r.high_severity_count or "-"}</td>'
            f'<td class="num medium">{r.medium_severity_count or "-"}</td>'
            f'<td class="num low">{r.low_severity_count or "-"}</td>'
            f'<td class="num">{r.duration_seconds}</td>'
            f'<td class="num">{inc_badge}</td>'
            f'<td class="model">{_escape(r.model)}</td>'
            "</tr>"
        )
    parts.append("</tbody></table>")
    return "\n".join(parts)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI PR Review Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f8fafc; color: #1e293b; padding: 24px; }}
  h1 {{ font-size: 24px; margin-bottom: 20px; color: #0f172a; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                 gap: 16px; margin-bottom: 32px; }}
  .stat-card {{ background: white; padding: 16px 20px; border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .stat-label {{ font-size: 13px; color: #64748b; margin-bottom: 6px; }}
  .stat-value {{ font-size: 28px; font-weight: 600; }}
  .history-table {{ width: 100%; background: white; border-radius: 8px;
                    overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    border-collapse: collapse; }}
  .history-table th {{ background: #f1f5f9; padding: 12px 16px; text-align: left;
                        font-size: 13px; color: #475569; font-weight: 600;
                        border-bottom: 1px solid #e2e8f0; }}
  .history-table td {{ padding: 10px 16px; font-size: 13px;
                        border-bottom: 1px solid #f1f5f9; }}
  .history-table tr:hover {{ background: #f8fafc; }}
  .num {{ text-align: center; font-variant-numeric: tabular-nums; }}
  .high {{ color: #ef4444; font-weight: 600; }}
  .medium {{ color: #f59e0b; font-weight: 600; }}
  .low {{ color: #10b981; }}
  .title a {{ color: #3b82f6; text-decoration: none; }}
  .title a:hover {{ text-decoration: underline; }}
  .time {{ color: #64748b; font-size: 12px; white-space: nowrap; }}
  .model {{ color: #64748b; font-size: 12px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
            font-size: 11px; background: #e2e8f0; color: #64748b; }}
  .badge-info {{ background: #dbeafe; color: #1e40af; }}
  .empty {{ text-align: center; padding: 40px; color: #64748b; }}
  .refresh {{ position: fixed; top: 24px; right: 24px;
              padding: 8px 16px; background: #3b82f6; color: white;
              border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }}
  .refresh:hover {{ background: #2563eb; }}
</style>
</head>
<body>
  <h1>AI PR Review Dashboard</h1>
  <button class="refresh" onclick="location.reload()">刷新</button>
  {stat_cards}
  {table}
</body>
</html>"""


def render_dashboard(records: Optional[list[AnalysisRecord]] = None) -> str:
    """渲染完整 Dashboard HTML 页面

    records: None 时自动从 history.load_records() 加载
    """
    if records is None:
        records = load_records()

    stats = compute_stats(records)
    stat_cards = _render_stat_cards(stats)
    table = _render_table(records)
    return _HTML_TEMPLATE.format(stat_cards=stat_cards, table=table)
