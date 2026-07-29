export function Settings() {
  return (
    <div>
      <h1>Settings</h1>
      <p className="muted">Per-user 配置（v0.11+ 计划）</p>
      <div className="empty-state">
        当前为 CLI 单用户模式，所有用户共享项目根目录的 <code>.ai-pr-review.yaml</code>。
      </div>
    </div>
  )
}