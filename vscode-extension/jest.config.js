/** Jest 配置：单元测试 ApiClient（无需 VS Code runtime） */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  testMatch: ['**/__tests__/**/*.test.ts'],
  testPathIgnorePatterns: ['/node_modules/', '/dist/'],
  // ApiClient 内部用 fetch()，需 jsdom 或 global fetch
  // node 环境默认没有 fetch（Node 18+ 有 globalThis.fetch）
  // 若 node < 18，需 polyfill
  transform: {
    '^.+\\.ts$': ['ts-jest', { tsconfig: 'tsconfig.json' }],
  },
};