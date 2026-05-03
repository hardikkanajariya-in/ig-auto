const state = {
  posts: [],
  inputFiles: [],
  summary: {},
  editingIndex: null,
  lastOutput: '',
};

const statusClasses = {
  pending: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  uploaded: 'bg-blue-100 text-blue-800 border-blue-200',
  publishing: 'bg-purple-100 text-purple-800 border-purple-200',
  published: 'bg-green-100 text-green-800 border-green-200',
  failed: 'bg-red-100 text-red-800 border-red-200',
  failed_retry: 'bg-orange-100 text-orange-800 border-orange-200',
};

const syncClasses = {
  ready_to_upload: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  missing_file: 'bg-red-100 text-red-800 border-red-200',
  uploaded_waiting: 'bg-blue-100 text-blue-800 border-blue-200',
  due_for_publish: 'bg-purple-100 text-purple-800 border-purple-200',
  publishing: 'bg-purple-100 text-purple-800 border-purple-200',
  published: 'bg-green-100 text-green-800 border-green-200',
  failed: 'bg-red-100 text-red-800 border-red-200',
  needs_review: 'bg-slate-100 text-slate-700 border-slate-200',
};

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatBytes(bytes = 0) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function badge(text, classes) {
  return `<span class="inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${classes}">${escapeHtml(text)}</span>`;
}

function datetimeLocalValue(value = '') {
  if (!value) return '';
  return String(value).replace(' ', 'T');
}

function jsonDateValue(value = '') {
  return String(value || '').replace('T', ' ');
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed: ${response.status}`);
  return data;
}

async function refreshData() {
  const data = await api('/api/posts');
  state.posts = data.posts || [];
  state.inputFiles = data.input_files || [];
  state.summary = data.summary || {};
  render();
}

function showOutput(title, result) {
  const stdout = result?.stdout || '';
  const stderr = result?.stderr || '';
  const code = result?.returncode ?? '';
  state.lastOutput = `${title}\nReturn code: ${code}\n\nSTDOUT:\n${stdout || '(empty)'}\n\nSTDERR:\n${stderr || '(empty)'}`;
  renderOutput();
}

async function runAction(button, label, endpoint) {
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = 'Running...';
  try {
    const result = await api(endpoint, { method: 'POST', body: '{}' });
    showOutput(label, result);
    await refreshData();
  } catch (error) {
    state.lastOutput = `${label}\nERROR: ${error.message}`;
    renderOutput();
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
}

function fillForm(post = null) {
  state.editingIndex = post?._index ?? null;
  document.querySelector('#formTitle').textContent = post ? `Edit Post #${post._index + 1}` : 'Create New Post';
  document.querySelector('#file').value = post?.file || '';
  document.querySelector('#type').value = post?.type || 'reel';
  document.querySelector('#publish_at').value = datetimeLocalValue(post?.publish_at || '');
  document.querySelector('#status').value = post?.status || 'pending';
  document.querySelector('#caption').value = post?.caption || '';
  document.querySelector('#formPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function submitForm(event) {
  event.preventDefault();
  const payload = {
    file: document.querySelector('#file').value,
    type: document.querySelector('#type').value,
    caption: document.querySelector('#caption').value,
    publish_at: jsonDateValue(document.querySelector('#publish_at').value),
    status: document.querySelector('#status').value,
  };

  const endpoint = state.editingIndex === null ? '/api/posts' : `/api/posts/${state.editingIndex}`;
  const method = state.editingIndex === null ? 'POST' : 'PUT';

  try {
    await api(endpoint, { method, body: JSON.stringify(payload) });
    state.editingIndex = null;
    document.querySelector('#postForm').reset();
    document.querySelector('#status').value = 'pending';
    await refreshData();
  } catch (error) {
    alert(error.message);
  }
}

async function deletePost(index) {
  if (!confirm('Delete this data.json record? This will not delete the media file.')) return;
  await api(`/api/posts/${index}`, { method: 'DELETE' });
  await refreshData();
}

async function markRetry(index) {
  await api(`/api/posts/${index}/mark-retry`, { method: 'POST', body: '{}' });
  await refreshData();
}

async function resetUpload(index) {
  if (!confirm('Reset upload fields and mark this post pending again?')) return;
  await api(`/api/posts/${index}/reset-upload`, { method: 'POST', body: '{}' });
  await refreshData();
}

async function loadLogs() {
  const data = await api('/api/logs');
  document.querySelector('#logs').textContent = data.logs || '(no logs yet)';
}

function renderSummary() {
  const items = [
    ['Total Posts', state.summary.total || 0],
    ['Pending', state.summary.pending || 0],
    ['Uploaded', state.summary.uploaded || 0],
    ['Due Publish', state.summary.due_for_publish || 0],
    ['Published', state.summary.published || 0],
    ['Failed', state.summary.failed || 0],
    ['Unsynced Files', state.summary.unsynced_files || 0],
    ['Missing Files', state.summary.missing_files || 0],
  ];

  return items.map(([label, value]) => `
    <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">${label}</p>
      <p class="mt-2 text-3xl font-bold text-slate-950">${value}</p>
    </div>
  `).join('');
}

function renderInputFiles() {
  if (!state.inputFiles.length) {
    return '<div class="rounded-2xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No files found in scheduler/input.</div>';
  }

  return state.inputFiles.map((file) => `
    <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3">
      <div>
        <p class="font-semibold text-slate-900">${escapeHtml(file.name)}</p>
        <p class="text-xs text-slate-500">${formatBytes(file.size_bytes)} • ${escapeHtml(file.suggested_type)}</p>
      </div>
      <div class="flex items-center gap-2">
        ${file.matched_in_data_json ? badge('matched', 'bg-green-100 text-green-800 border-green-200') : badge('unsynced', 'bg-orange-100 text-orange-800 border-orange-200')}
        <button class="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-700" data-create-file="${escapeHtml(file.name)}" data-file-type="${escapeHtml(file.suggested_type)}">Create Record</button>
      </div>
    </div>
  `).join('');
}

function renderPostsTable() {
  if (!state.posts.length) {
    return '<div class="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">No posts in data.json yet.</div>';
  }

  const rows = state.posts.map((post) => `
    <tr class="border-b border-slate-100 align-top">
      <td class="px-3 py-3 text-sm text-slate-500">${post._index + 1}</td>
      <td class="px-3 py-3"><p class="font-semibold text-slate-900">${escapeHtml(post.file)}</p><p class="text-xs text-slate-500">${post.file_exists ? 'File found' : 'File missing/not needed'}</p></td>
      <td class="px-3 py-3 text-sm">${escapeHtml(post.type || '')}</td>
      <td class="px-3 py-3 text-sm whitespace-nowrap">${escapeHtml(post.publish_at || '')}</td>
      <td class="px-3 py-3">${badge(post.status || 'pending', statusClasses[post.status] || statusClasses.pending)}</td>
      <td class="px-3 py-3">${badge(post.sync_status, syncClasses[post.sync_status] || syncClasses.needs_review)}</td>
      <td class="px-3 py-3 max-w-md text-sm text-slate-600">${escapeHtml(post.caption || '').slice(0, 140)}${(post.caption || '').length > 140 ? '...' : ''}</td>
      <td class="px-3 py-3">
        <div class="flex flex-wrap gap-2">
          <button class="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold hover:bg-slate-50" data-edit="${post._index}">Edit</button>
          <button class="rounded-md border border-orange-200 px-2 py-1 text-xs font-semibold text-orange-700 hover:bg-orange-50" data-retry="${post._index}">Retry</button>
          <button class="rounded-md border border-blue-200 px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50" data-reset="${post._index}">Reset</button>
          <button class="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50" data-delete="${post._index}">Delete</button>
        </div>
      </td>
    </tr>
  `).join('');

  return `<div class="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm"><table class="min-w-full text-left"><thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th class="px-3 py-3">#</th><th class="px-3 py-3">File</th><th class="px-3 py-3">Type</th><th class="px-3 py-3">Publish At</th><th class="px-3 py-3">Status</th><th class="px-3 py-3">Sync</th><th class="px-3 py-3">Caption</th><th class="px-3 py-3">Actions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderOutput() {
  const output = document.querySelector('#output');
  if (output) output.textContent = state.lastOutput || 'Run upload or publish to see output here.';
}

function bindEvents() {
  document.querySelector('#refreshBtn')?.addEventListener('click', refreshData);
  document.querySelector('#uploadBtn')?.addEventListener('click', (event) => runAction(event.currentTarget, 'Upload Preparation', '/api/trigger/upload'));
  document.querySelector('#publishBtn')?.addEventListener('click', (event) => runAction(event.currentTarget, 'Publish Once', '/api/trigger/publish'));
  document.querySelector('#logsBtn')?.addEventListener('click', loadLogs);
  document.querySelector('#postForm')?.addEventListener('submit', submitForm);
  document.querySelector('#cancelEdit')?.addEventListener('click', () => fillForm(null));

  document.querySelectorAll('[data-create-file]').forEach((button) => {
    button.addEventListener('click', () => fillForm({ file: button.dataset.createFile, type: button.dataset.fileType || 'reel', status: 'pending' }));
  });
  document.querySelectorAll('[data-edit]').forEach((button) => button.addEventListener('click', () => fillForm(state.posts[Number(button.dataset.edit)])));
  document.querySelectorAll('[data-delete]').forEach((button) => button.addEventListener('click', () => deletePost(Number(button.dataset.delete))));
  document.querySelectorAll('[data-retry]').forEach((button) => button.addEventListener('click', () => markRetry(Number(button.dataset.retry))));
  document.querySelectorAll('[data-reset]').forEach((button) => button.addEventListener('click', () => resetUpload(Number(button.dataset.reset))));
}

function render() {
  document.querySelector('#app').innerHTML = `
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <header class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p class="text-sm font-semibold uppercase tracking-wide text-blue-600">Local JSON + input folder manager</p>
            <h1 class="mt-2 text-3xl font-bold tracking-tight text-slate-950">Instagram Scheduler Control Panel</h1>
            <p class="mt-2 max-w-3xl text-sm text-slate-600">Local use only. Manage scheduler/data.json, inspect scheduler/input, trigger upload preparation, and test one-run publishing without exposing secrets in the browser.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button id="refreshBtn" class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold hover:bg-slate-50">Refresh</button>
            <button id="uploadBtn" class="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">Run Upload Preparation</button>
            <button id="publishBtn" class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700">Run Publish Once</button>
          </div>
        </div>
        <div class="mt-4 rounded-2xl border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-900">This dashboard binds to localhost only. Do not expose it publicly. Secrets are never displayed here.</div>
      </header>

      <section class="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">${renderSummary()}</section>

      <section class="mt-6 grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
        <div id="formPanel" class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 id="formTitle" class="text-xl font-bold text-slate-950">Create New Post</h2>
          <form id="postForm" class="mt-4 space-y-4">
            <div><label class="text-sm font-semibold text-slate-700">File</label><input id="file" list="fileOptions" class="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" required /><datalist id="fileOptions">${state.inputFiles.map((file) => `<option value="${escapeHtml(file.name)}"></option>`).join('')}</datalist></div>
            <div class="grid gap-4 sm:grid-cols-2"><div><label class="text-sm font-semibold text-slate-700">Type</label><select id="type" class="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"><option value="image">image</option><option value="reel">reel</option><option value="image_reel">image_reel</option><option value="video">video</option></select></div><div><label class="text-sm font-semibold text-slate-700">Status</label><select id="status" class="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"><option value="pending">pending</option><option value="uploaded">uploaded</option><option value="failed_retry">failed_retry</option><option value="failed">failed</option><option value="published">published</option></select></div></div>
            <div><label class="text-sm font-semibold text-slate-700">Publish At</label><input id="publish_at" type="datetime-local" class="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" required /></div>
            <div><label class="text-sm font-semibold text-slate-700">Caption</label><textarea id="caption" rows="8" class="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" required></textarea></div>
            <div class="flex gap-2"><button class="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white">Save Record</button><button type="button" id="cancelEdit" class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold">Clear</button></div>
          </form>
        </div>

        <div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="mb-4 flex items-center justify-between"><h2 class="text-xl font-bold text-slate-950">Input Files</h2><span class="text-sm text-slate-500">scheduler/input</span></div>
          <div class="space-y-3">${renderInputFiles()}</div>
        </div>
      </section>

      <section class="mt-6"><div class="mb-4 flex items-center justify-between"><h2 class="text-xl font-bold text-slate-950">Posts</h2><span class="text-sm text-slate-500">scheduler/data.json</span></div>${renderPostsTable()}</section>

      <section class="mt-6 grid gap-6 lg:grid-cols-2">
        <div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><h2 class="text-xl font-bold text-slate-950">Command Output</h2><pre id="output" class="mt-4 max-h-96 overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">${escapeHtml(state.lastOutput || 'Run upload or publish to see output here.')}</pre></div>
        <div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><div class="flex items-center justify-between"><h2 class="text-xl font-bold text-slate-950">Logs</h2><button id="logsBtn" class="rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold hover:bg-slate-50">Refresh Logs</button></div><pre id="logs" class="mt-4 max-h-96 overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">Click Refresh Logs to load recent logs.</pre></div>
      </section>
    </div>
  `;
  bindEvents();
}

refreshData().catch((error) => {
  document.querySelector('#app').innerHTML = `<div class="p-6"><div class="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-800">${escapeHtml(error.message)}</div></div>`;
});
