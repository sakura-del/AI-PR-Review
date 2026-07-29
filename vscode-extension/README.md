# AI PR Review VS Code Extension

VS Code extension for [AI PR Review](https://github.com/sakura-del/AI-PR-Review) — call v0.10 FastAPI web backend, show AI review results inline in your editor.

## Features

- 🤖 **One-command PR review**: paste a GitHub PR URL → submit to backend → poll for results → display in Markdown Webview
- 🔍 **Inline CodeLens**: after review, each finding appears as a lens above the relevant line — click to see details
- 📊 **Sidebar Dashboard**: stats cards (total / high / medium / low / avg duration) + jobs table with 5s auto-refresh
- 🔐 **GitHub OAuth + PAT support**: log in via browser, or paste a Personal Access Token (Read+Write pull_requests scope)

## Requirements

- VS Code 1.85+
- The [AI PR Review web backend](https://github.com/sakura-del/AI-PR-Review) running locally or on your server (default: `http://127.0.0.1:8765`)

## Setup

1. Install this extension:
   ```bash
   # From .vsix file
   code --install-extension ai-pr-review-1.0.0.vsix
   ```

2. Start the AI PR Review web backend (in the main project repo):
   ```bash
   ai-pr-review serve --web --port 8765
   ```

3. (Optional) Configure the API base URL in VS Code settings:
   - `ai-pr-review.apiBaseUrl` (default: `http://127.0.0.1:8765`)

## Commands

| Command | Description |
| --- | --- |
| `AI PR Review: Login to GitHub` | Open browser OAuth OR paste a PAT |
| `AI PR Review: Logout` | Clear stored token |
| `AI PR Review: Show User` | Display logged-in GitHub user |
| `AI PR Review: Review PR` | Submit a PR URL for review, show Markdown result |
| `AI PR Review: Show Job` | Look up a specific job by ID |
| `AI PR Review: Show Dashboard` | Open sidebar with stats + jobs (5s auto-refresh) |

After running `Review PR` successfully, the affected files get inline CodeLens — click any lens to see the finding detail.

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `ai-pr-review.apiBaseUrl` | `http://127.0.0.1:8765` | Backend base URL |
| `ai-pr-review.githubToken` | (empty) | Personal Access Token (Read+Write pull_requests) |
| `ai-pr-review.defaultExpert` | `security` | Default expert when reviewing a single file |

The GitHub token is stored in VS Code's encrypted SecretStorage (not in plaintext settings).

## Development

```bash
# Install deps
npm install

# Watch build
npm run watch

# Type check
npm run typecheck

# Package .vsix
npm run package
```

## Architecture

```
VS Code Extension (TypeScript)
  ↓ HTTP
FastAPI Web Backend (v0.10)
  ↓ async JobQueue
AI Analysis (DeepSeek / Qwen / GLM)
  ↓
GitHub API (PR + 评论回写)
```

- `src/api/client.ts` — typed HTTP client for `/api/*` endpoints
- `src/commands/` — command implementations (auth, review, dashboard)
- `src/providers/codelens.ts` — inline CodeLens for findings
- `src/webview/` — (planned v1.1) custom editor for review results
- `src/config.ts` — settings + SecretStorage wrapper

## Roadmap

- v1.0 (current): PR review + Webview + CodeLens
- v1.1: Auto-detect PR from current branch (git remote + PR ref)
- v1.2: Inline fix suggestions ("Apply Fix" button)
- v2.0: VS Code Marketplace publish

## License

MIT
