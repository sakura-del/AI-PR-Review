# 增量分析功能 - 收尾计划

## 当前状态

增量分析功能**已全部实现**，123 个测试通过。核心模块：

| 文件 | 状态 | 说明 |
|------|------|------|
| `incremental.py` | ✅ 已完成 | IncrementalAnalyzer 类 |
| `history.py` | ✅ 已完成 | AnalysisRecord 扩展 + find_last_record() |
| `github_client.py` | ✅ 已完成 | get_pr_head_sha() + get_commit_diff() |
| `prompt_templates.py` | ✅ 已完成 | INCREMENTAL_SYSTEM_PROMPT + incremental_context |
| `analyzer.py` | ✅ 已完成 | analyze_incremental() 方法 |
| `cli.py` | ✅ 已完成 | --incremental/-i 参数 + 增量分析流程 |
| `test_incremental.py` | ✅ 已完成 | 13 个测试用例 |
| `README.md` | 🔄 需更新 | "未来扩展方向"仍将已实现功能列为待开发 |

## 剩余工作

### Step 1: 更新 README.md "未来扩展方向" 章节

README 第 344-350 行的"未来扩展方向"中，以下两项已实现，需要移除或标记为已完成：

- `2. **增量分析** - 多次提交时仅分析增量变更` → **已实现**
- `5. **自定义专家** - 用户自定义审查标准和 checklist` → **已实现**

修改方案：
- 将已实现的两项从"未来扩展方向"中移除
- 保留真正待开发的项目（GitHub App 集成、团队规范学习、IDE 插件）
- 可选：新增"已实现扩展"子章节展示增量分析和自定义专家功能

### Step 2: 运行全部测试验证

```bash
pytest tests/ -v
```

确保 123 个测试全部通过，无回归。

### Step 3: Commit 并推送到 GitHub

```bash
git add -A
git commit -m "feat: 增量分析功能 - 仅分析自上次审查以来的新增变更

- 新增 incremental.py 增量分析模块
- 扩展 history.py 支持 SHA 追踪和记录查找
- 扩展 github_client.py 支持 commit diff 获取
- 新增 INCREMENTAL_SYSTEM_PROMPT 增量专用提示
- analyzer.py 新增 analyze_incremental() 方法
- cli.py 新增 --incremental/-i 参数
- 新增 13 个增量分析测试用例
- 更新 README.md 反映已实现功能"

git push origin main
```

## 风险点

- GitHub push 可能因网络问题失败（之前遇到过 Connection was reset），需重试
- 确保所有文件变更都已暂存（包括新建的 incremental.py 和 test_incremental.py）
