/**
 * ApiClient 单元测试（不需要 VS Code runtime）
 *
 * 用全局 fetch mock 验证请求 URL、method、headers、body 解析
 */
import { ApiClient, ApiError } from '../api/client';

// 保存原始 fetch，测试后恢复
const originalFetch = global.fetch;

describe('ApiClient', () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn();
    (global as any).fetch = fetchMock;
  });

  afterAll(() => {
    global.fetch = originalFetch;
  });

  function mockJsonResponse(body: unknown, status = 200): Response {
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: status === 200 ? 'OK' : 'Error',
      json: async () => body,
      text: async () => JSON.stringify(body),
    } as Response;
  }

  test('health() 调 GET /api/health', async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({ status: 'ok', version: '0.10.0' })
    );
    const api = new ApiClient({ baseUrl: 'http://localhost:8765' });
    const r = await api.health();
    expect(r.status).toBe('ok');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8765/api/health',
      expect.objectContaining({ method: 'GET' })
    );
  });

  test('submitJob() 用 POST + JSON body', async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({ job_id: 'abc123', status: 'pending', pr_url: 'https://...' })
    );
    const api = new ApiClient({ baseUrl: 'http://localhost:8765' });
    await api.submitJob('https://github.com/o/r/pull/1');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8765/api/jobs/',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ pr_url: 'https://github.com/o/r/pull/1' }),
      })
    );
  });

  test('token 在 headers 中加 Authorization', async () => {
    fetchMock.mockResolvedValue(mockJsonResponse({}));
    const api = new ApiClient({
      baseUrl: 'http://localhost:8765',
      token: 'github_pat_11...',
    });
    await api.health();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'token github_pat_11...',
        }),
      })
    );
  });

  test('404 抛 ApiError 含 status + body', async () => {
    fetchMock.mockResolvedValue(mockJsonResponse({ error: 'not found' }, 404));
    const api = new ApiClient({ baseUrl: 'http://localhost:8765' });
    await expect(api.getJob('xxx')).rejects.toThrow(ApiError);
    try {
      await api.getJob('xxx');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.status).toBe(404);
      expect(e.body).toContain('not found');
    }
  });

  test('authMe 解析 authenticated + user 字段', async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        authenticated: true,
        user_id: '42',
        github_login: 'sakura-del',
      })
    );
    const api = new ApiClient({ baseUrl: 'http://localhost:8765' });
    const me = await api.authMe();
    expect(me.authenticated).toBe(true);
    expect(me.github_login).toBe('sakura-del');
  });
});