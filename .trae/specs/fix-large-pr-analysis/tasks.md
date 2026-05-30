# Tasks

- [x] Task 1: 修复 Severity 枚举 P0-P3 兼容映射
  - [x] SubTask 1.1: 在 `analyzer.py` 中新增 `_normalize_severity()` 函数，将 P0→HIGH, P1→MEDIUM, P2→MEDIUM, P3→LOW
  - [x] SubTask 1.2: 修改 `parse_ai_response()` 中 findings 解析，使用 `_normalize_severity()` 替代直接 `Severity()` 构造
  - [x] SubTask 1.3: 修改 suggestions 解析同理，对 priority 字段做 P0-P3 兼容

- [x] Task 2: 修复 OUTPUT_SCHEMA 字段名不一致
  - [x] SubTask 2.1: 将 `prompt_templates.py` 中 OUTPUT_SCHEMA 的 `"changes"` 改为 `"key_changes"`，与 parse_ai_response 保持一致
  - [x] SubTask 2.2: 同步更新 FEW_SHOT_EXAMPLE 中的字段名

- [x] Task 3: 启用大 PR 分片分析
  - [x] SubTask 3.1: 修改 `cli.py` review 命令，在调用分析前判断 `_should_shard(parsed_diff)`
  - [x] SubTask 3.2: 需要分片时调用 `analyzer.analyze_with_shards()`，否则调用 `analyzer.analyze()`
  - [x] SubTask 3.3: 分片分析时显示进度信息（如 "Sharding analysis into N parts..."）

- [x] Task 4: 动态上下文预算
  - [x] SubTask 4.1: 在 `context_builder.py` 中根据 ParsedDiff 大小动态调整 budget
  - [x] SubTask 4.2: 大 PR（变更行数 > 5000）时 budget 提升至 12000

- [x] Task 5: 可配置 confidence 过滤阈值
  - [x] SubTask 5.1: 在 `config.py` 的 `AnalysisConfig` 中新增 `min_confidence: int = 2`
  - [x] SubTask 5.2: 修改 `_apply_filters()` 使用配置值替代硬编码 3
  - [x] SubTask 5.3: CLI 新增 `--min-confidence` 参数

- [x] Task 6: 编写和更新测试
  - [x] SubTask 6.1: 测试 P0-P3 severity 映射正确性
  - [x] SubTask 6.2: 测试 parse_ai_response 对混合格式 severity 的容错
  - [x] SubTask 6.3: 测试 OUTPUT_SCHEMA 字段名一致性
  - [x] SubTask 6.4: 测试 _should_shard 判断逻辑
  - [x] SubTask 6.5: 测试动态上下文预算

- [x] Task 7: 端到端验证
  - [x] SubTask 7.1: 运行全部测试确保无回归
  - [x] SubTask 7.2: 对目标 PR 执行实际审查验证输出完整性

# Task Dependencies
- [Task 2] depends on [Task 1] (字段名修复和 severity 修复都在 parse_ai_response 中)
- [Task 3] depends on nothing (独立修改 cli.py)
- [Task 4] depends on nothing (独立修改 context_builder.py)
- [Task 5] depends on nothing (独立修改 config + analyzer)
- [Task 6] depends on [Task 1, 2, 3, 4, 5]
- [Task 7] depends on [Task 6]
