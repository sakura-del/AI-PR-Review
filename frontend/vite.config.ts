import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// Vite config for AI PR Review SPA
// - Base path: /static/（被 FastAPI 挂载在 /static）
// - Dev server: http://localhost:5173 (proxies /api → backend)
// - Build: 输出到 ../src/ai_pr_review/server/static/（被 FastAPI 静态服务）

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: resolve(__dirname, '../src/ai_pr_review/server/static'),
    emptyOutDir: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8765',
      '/auth': 'http://localhost:8765',
    },
  },
})