/* AI PR Review Dashboard SPA — vanilla JS + 简单 hash 路由 */

const state = {
  user: null,
  apiBase: '',  // 同一 origin
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(path, opts = {}) {
  const resp = await fetch(state.apiBase + path, {
    credentials: 'same-origin',
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.status === 204 ? null : resp.json();
}

async function checkAuth() {
  try {
    state.user = await api('/auth/me');
    if (state.user.authenticated) {
      $('#nav').classList.remove('hidden');
      $('#login-link').classList.add('hidden');
      $('#user-info').textContent = '@' + state.user.github_login;
    }
  } catch (e) {
    console.warn('Auth check failed:', e);
  }
}

// ===== 路由（hash 模式，避免 Vite dev server 配置）=====

function parseRoute() {
  const hash = window.location.hash || '#/';
  return hash.replace(/^#/, '');
}

function navigate(route) {
  window.location.hash = '#' + route;
}

function showView(route) {
  $$('.view').forEach(v => v.classList.add('hidden'));
  $$('.nav a').forEach(a => a.classList.remove('active'));
  const targetView = $(`#${route}-view`);
  if (targetView) targetView.classList.remove('hidden');
  const navLink = $(`.nav a[data-route="${route}"]`);
  if (navLink) navLink.classList.add('active');
  return route;
}

window.addEventListener('hashchange', () => {
  showView(parseRoute());
});

// ===== Dashboard 数据加载 =====

async function loadDashboard() {
  try {
    const stats = await api('/api/stats');
    $('#stat-total').textContent = stats.total;
    $('#stat-high').textContent = stats.high;
    $('#stat-medium').textContent = stats.medium;
    $('#stat-avg-duration').textContent = stats.avg_duration.toFixed(2);
  } catch (e) {
    showError('加载统计失败：' + e.message);
  }

  try {
    const records = await api('/api/history?limit=20');
    const tbody = $('#recent-tbody');
    if (!records.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">暂无审查记录</td></tr>';
      return;
    }
    tbody.innerHTML = records.map(r => `
      <tr>
        <td>${formatTime(r.timestamp)}</td>
        <td><a href="${r.pr_url}" target="_blank">${escapeHtml(r.pr_title.slice(0, 50))}</a></td>
        <td class="num high">${r.high_severity_count || '-'}</td>
        <td class="num medium">${r.medium_severity_count || '-'}</td>
        <td class="num low">${r.low_severity_count || '-'}</td>
        <td class="num">${r.duration_seconds}s</td>
      </tr>
    `).join('');
  } catch (e) {
    showError('加载历史失败：' + e.message);
  }
}

async function loadJobs() {
  try {
    const jobs = await api('/api/jobs');
    const tbody = $('#jobs-tbody');
    if (!jobs.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">暂无任务</td></tr>';
      return;
    }
    tbody.innerHTML = jobs.map(j => `
      <tr>
        <td><code>${j.id.slice(0, 8)}</code></td>
        <td><a href="${j.pr_url}" target="_blank">${escapeHtml(j.pr_url)}</a></td>
        <td><span class="status-${j.status}">${j.status}</span></td>
        <td>${formatTime(j.created_at)}</td>
        <td>${j.finished_at ? formatTime(j.finished_at) : '-'}</td>
      </tr>
    `).join('');
  } catch (e) {
    showError('加载任务失败：' + e.message);
  }
}

// ===== Submit PR =====

async function submitPR(prUrl) {
  try {
    const job = await api('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ pr_url: prUrl }),
    });
    showError('');  // clear
    navigate('jobs');
    loadJobs();
    return job;
  } catch (e) {
    showError('提交失败：' + e.message);
    throw e;
  }
}

// ===== Utilities =====

function formatTime(iso) {
  if (!iso) return '-';
  return iso.slice(0, 19).replace('T', ' ');
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s || '';
  return div.innerHTML;
}

function showError(msg) {
  const banner = $('#error-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'error-banner';
    banner.className = 'error-banner';
    document.querySelector('main').prepend(banner);
  }
  banner.textContent = msg;
  banner.classList.toggle('visible', !!msg);
}

// ===== 启动 =====

window.addEventListener('DOMContentLoaded', async () => {
  await checkAuth();
  showView(parseRoute());
  loadDashboard();

  $('#submit-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = $('#pr-url').value.trim();
    if (!url) return;
    await submitPR(url);
  });
});