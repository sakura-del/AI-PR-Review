# 修复大 PR 分析输出缺失问题 Spec

## Why
对大型 PR（如 556 文件、+40180/-8937 行）执行审查时，工具仅输出"PR 变更总结"，缺失"风险识别"和"Review 建议"部分。根本原因是 Severity 枚举与 prompt 输出格式不匹配、分片分析未被调用、上下文预算不足等多个缺陷叠加，导致 AI 返回的 findings 和 suggestions 被静默丢弃。

## What Changes
- **修复 Severity 枚举映射**：将 P0-P3 映射到 high/medium/low，或扩展枚举支持 P0-P3
- **修复 parse_ai_response 字段名不一致**：OUTPUT_SCHEMA 中 `"changes"` 与代码中 `"key_changes"` 不匹配
- **启用分片分析**：CLI 中对大 PR 调用 `analyze_with_shards()` 替代 `analyze()`
- **提升上下文预算**：大 PR 场景下动态增加 context_budget
- **降低 confidence 过滤阈值**：从硬编码 3 降为可配置，默认 2
- **增强 AI 响应解析容错**：对 P0-P3 格式的 severity 做兼容转换

## Impact
- Affected specs: 核心分析流程、终端输出、GitHub 评论
- Affected code: `analyzer.py`、`models.py`、`cli.py`、`context_builder.py`、`prompt_templates.py`

## ADDED Requirements

### Requirement: P0-P3 Severity 兼容映射
系统 SHALL 将 AI 输出的 P0-P3 严重级别正确映射为内部 Severity 枚举值，不再静默丢弃 findings。

#### Scenario: AI 返回 P0-P3 格式
- **WHEN** AI 响应中 findings 的 severity 字段为 "P0"/"P1"/"P2"/"P3"
- **THEN** 系统将其映射为 HIGH/MEDIUM/MEDIUM/LOW，而非抛出 ValueError 丢弃

#### Scenario: AI 返回 high/medium/low 格式
- **WHEN** AI 响应中 findings 的 severity 字段为 "high"/"medium"/"low"
- **THEN** 系统正常解析，行为不变

### Requirement: 大 PR 自动分片分析
系统 SHALL 在 PR 文件数超过阈值时自动启用分片分析，确保每个分片都能获得完整的 findings 和 suggestions。

#### Scenario: PR 文件数超过 SHARD_FILE_THRESHOLD
- **WHEN** PR 包含超过 20 个文件或变更行数超过 5000
- **THEN** CLI 自动调用 `analyze_with_shards()` 而非 `analyze()`
- **AND** 终端显示分片进度信息

#### Scenario: PR 文件数在阈值内
- **WHEN** PR 文件数 ≤ 20 且变更行数 ≤ 5000
- **THEN** CLI 调用 `analyze()`，行为不变

### Requirement: 动态上下文预算
系统 SHALL 根据 PR 大小动态调整上下文预算，避免大 PR 的 diff 被过度截断。

#### Scenario: 大 PR 场景
- **WHEN** PR 变更行数超过 5000
- **THEN** context_budget 自动提升至 12000 tokens

#### Scenario: 普通 PR 场景
- **WHEN** PR 变更行数 ≤ 5000
- **THEN** context_budget 保持默认 6000 tokens

### Requirement: 可配置 confidence 过滤阈值
系统 SHALL 支持配置 confidence 过滤阈值，默认值从 3 降为 2，减少有效 findings 被误过滤。

#### Scenario: 使用默认阈值
- **WHEN** 用户未指定 confidence 阈值
- **THEN** 系统使用默认值 2 过滤低置信度 findings

### Requirement: OUTPUT_SCHEMA 字段名一致性
系统 SHALL 确保 prompt 中的 OUTPUT_SCHEMA 字段名与 parse_ai_response 解析逻辑一致。

#### Scenario: AI 返回 "changes" 字段
- **WHEN** AI 按 OUTPUT_SCHEMA 返回 `"changes"` 字段
- **THEN** parse_ai_response 正确解析为 `key_changes`

## MODIFIED Requirements

### Requirement: parse_ai_response 严重级别解析
原实现直接使用 `Severity(f.get("severity", "low"))`，仅支持 high/medium/low。
修改为：先尝试 P0-P3 映射，再尝试原有 high/medium/low，最后默认 low。

### Requirement: CLI review 命令分析流程
原实现始终调用 `analyzer.analyze()`。
修改为：根据 `_should_shard()` 判断是否需要分片，需要时调用 `analyze_with_shards()`。

### Requirement: _apply_filters confidence 过滤
原实现硬编码 `confidence >= 3`。
修改为：使用可配置阈值，默认 2。

## REMOVED Requirements
无
