import express from 'express';
import { createServer as createViteServer } from 'vite';
import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const __filename = fileURLToPath(import.meta.url);
const WEB_UI_DIR = path.dirname(__filename);
const BASE_DIR = path.resolve(WEB_UI_DIR, '..');
const SCHEDULER_DIR = path.join(BASE_DIR, 'scheduler');
const DATA_JSON = path.join(SCHEDULER_DIR, 'data.json');
const INPUT_DIR = path.join(SCHEDULER_DIR, 'input');
const LOG_DIR = path.join(SCHEDULER_DIR, 'logs');

const HOST = '127.0.0.1';
const PORT = 5050;
const TIME_ZONE = 'Asia/Kolkata';
const allowedTypes = new Set(['image', 'reel', 'image_reel', 'video']);
const allowedStatuses = new Set(['pending', 'uploaded', 'publishing', 'published', 'failed', 'failed_retry']);
const imageExtensions = new Set(['.jpg', '.jpeg', '.png', '.webp']);
const videoExtensions = new Set(['.mp4', '.mov']);
const logFiles = ['ig_prepare_uploads.log', 'ig_publish_once.log', 'ig_auto_scheduler.log'];

let processRunning = false;

function nowKolkata() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(new Date());
  const get = (type) => parts.find((part) => part.type === type)?.value || '00';
  return new Date(`${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}:${get('second')}+05:30`);
}

function timestampKolkata() {
  const date = nowKolkata();
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function parsePublishAt(value) {
  if (!value || typeof value !== 'string') throw new Error('publish_at is required');
  const normalized = value.trim().replace('T', ' ');
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/);
  if (!match) throw new Error('publish_at must be YYYY-MM-DD HH:MM');
  const [, y, m, d, h, min] = match.map(Number);
  return new Date(Date.UTC(y, m - 1, d, h - 5, min - 30, 0));
}

function normalizePublishAt(value) {
  const normalized = String(value || '').trim().replace('T', ' ');
  parsePublishAt(normalized);
  return normalized;
}

function safeFilename(filename) {
  const value = String(filename || '').trim();
  if (!value) throw new Error('file is required');
  if (value.includes('/') || value.includes('\\') || value.includes('..')) {
    throw new Error('file must be a plain filename inside scheduler/input');
  }
  return value;
}

function suggestedTypeForName(filename) {
  const ext = path.extname(filename).toLowerCase();
  if (imageExtensions.has(ext)) return 'image';
  if (videoExtensions.has(ext)) return 'reel';
  return 'unknown';
}

async function ensureDirs() {
  await fs.mkdir(INPUT_DIR, { recursive: true });
  await fs.mkdir(LOG_DIR, { recursive: true });
  if (!existsSync(DATA_JSON)) await savePosts([]);
}

async function loadPosts() {
  await ensureDirs();
  const raw = await fs.readFile(DATA_JSON, 'utf8');
  const data = JSON.parse(raw || '[]');
  if (!Array.isArray(data)) throw new Error('data.json must be a valid JSON array');
  return data;
}

async function savePosts(posts) {
  await fs.mkdir(path.dirname(DATA_JSON), { recursive: true });
  const tempPath = DATA_JSON.replace(/\.json$/, '.tmp.json');
  await fs.writeFile(tempPath, JSON.stringify(posts, null, 2), 'utf8');
  await fs.rename(tempPath, DATA_JSON);
}

async function listInputFiles() {
  await ensureDirs();
  const entries = await fs.readdir(INPUT_DIR, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isFile() || entry.name === '.gitkeep') continue;
    const filePath = path.join(INPUT_DIR, entry.name);
    const stat = await fs.stat(filePath);
    files.push({
      name: entry.name,
      size_bytes: stat.size,
      extension: path.extname(entry.name).toLowerCase(),
      suggested_type: suggestedTypeForName(entry.name),
    });
  }
  return files;
}

function computePostUi(post, index, inputNames) {
  const fileName = String(post.file || '').trim();
  const status = String(post.status || 'pending').toLowerCase();
  const publishAtRaw = String(post.publish_at || '').trim();
  const cloudinaryUrl = String(post.cloudinary_url || '').trim();
  const fileExists = inputNames.has(fileName);
  const isUploaded = Boolean(cloudinaryUrl) || ['uploaded', 'publishing', 'published'].includes(status);
  let isDue = false;
  let isFuture = false;
  let isOutdated = false;

  if (publishAtRaw) {
    try {
      const publishTime = parsePublishAt(publishAtRaw);
      const now = nowKolkata();
      isDue = publishTime <= now;
      isFuture = publishTime > now;
    } catch {
      isOutdated = true;
    }
  }

  let syncStatus = 'needs_review';
  if (status === 'pending' && fileExists) syncStatus = 'ready_to_upload';
  else if (status === 'pending' && !fileExists) syncStatus = 'missing_file';
  else if (status === 'uploaded' && isFuture) syncStatus = 'uploaded_waiting';
  else if (status === 'uploaded' && isDue) syncStatus = 'due_for_publish';
  else if (status === 'publishing') syncStatus = 'publishing';
  else if (status === 'published') syncStatus = 'published';
  else if (['failed', 'failed_retry'].includes(status)) syncStatus = 'failed';

  if ((status === 'pending' || status === 'uploaded') && isDue) isOutdated = true;

  return {
    ...post,
    _index: index,
    file_exists: fileExists,
    matched_input_file: fileExists,
    is_uploaded: isUploaded,
    is_due: isDue,
    is_future: isFuture,
    is_outdated: isOutdated,
    sync_status: syncStatus,
  };
}

async function dashboardData() {
  const posts = await loadPosts();
  const inputFiles = await listInputFiles();
  const inputNames = new Set(inputFiles.map((file) => file.name));
  const recordNames = new Set(posts.map((post) => String(post.file || '').trim()).filter(Boolean));
  const enrichedPosts = posts.map((post, index) => computePostUi(post, index, inputNames));

  for (const inputFile of inputFiles) inputFile.matched_in_data_json = recordNames.has(inputFile.name);

  return {
    posts: enrichedPosts,
    input_files: inputFiles,
    summary: {
      total: posts.length,
      pending: posts.filter((post) => String(post.status || 'pending').toLowerCase() === 'pending').length,
      uploaded: posts.filter((post) => String(post.status || '').toLowerCase() === 'uploaded').length,
      publishing: posts.filter((post) => String(post.status || '').toLowerCase() === 'publishing').length,
      published: posts.filter((post) => String(post.status || '').toLowerCase() === 'published').length,
      failed: posts.filter((post) => ['failed', 'failed_retry'].includes(String(post.status || '').toLowerCase())).length,
      missing_files: enrichedPosts.filter((post) => post.sync_status === 'missing_file').length,
      unsynced_files: inputFiles.filter((file) => !file.matched_in_data_json).length,
      outdated_records: enrichedPosts.filter((post) => post.is_outdated).length,
      due_for_publish: enrichedPosts.filter((post) => post.sync_status === 'due_for_publish').length,
    },
  };
}

function validatePostPayload(payload, existingPosts, editIndex = null) {
  const file = safeFilename(payload.file);
  const caption = String(payload.caption || '').trim();
  const publish_at = normalizePublishAt(payload.publish_at);
  const type = String(payload.type || suggestedTypeForName(file)).toLowerCase();
  const status = String(payload.status || 'pending').toLowerCase();

  if (!caption) throw new Error('caption is required');
  if (!allowedTypes.has(type) || type === 'unknown') throw new Error('type must be image, reel, image_reel, or video');
  if (!allowedStatuses.has(status)) throw new Error('unsupported status');

  existingPosts.forEach((post, index) => {
    if (editIndex !== null && index === editIndex) return;
    if (String(post.file || '').trim() === file) throw new Error('a data.json record already exists for this file');
  });

  return { file, type, caption, publish_at, status };
}

function resetUploadFields(post) {
  const cleaned = { ...post };
  for (const key of [
    'cloudinary_url',
    'cloudinary_public_id',
    'cloudinary_resource_type',
    'uploaded_at',
    'creation_id',
    'published_media_id',
    'published_at',
    'cloudinary_deleted',
    'failed_at',
    'message',
  ]) delete cleaned[key];
  cleaned.status = 'pending';
  cleaned.updated_at = timestampKolkata();
  return cleaned;
}

function runSchedulerScript(scriptName) {
  return new Promise((resolve) => {
    if (processRunning) {
      resolve({ ok: false, stdout: '', stderr: 'another scheduler process is already running', returncode: 409 });
      return;
    }

    processRunning = true;
    const scriptPath = path.join(SCHEDULER_DIR, scriptName);
    const child = spawn('python', [scriptPath], { cwd: SCHEDULER_DIR, shell: true });
    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (data) => { stdout += data.toString(); });
    child.stderr.on('data', (data) => { stderr += data.toString(); });
    child.on('close', (code) => {
      processRunning = false;
      resolve({ ok: code === 0, stdout, stderr, returncode: code });
    });
    child.on('error', (error) => {
      processRunning = false;
      resolve({ ok: false, stdout, stderr: String(error.message || error), returncode: 1 });
    });
  });
}

async function readLogs(limit = 200) {
  const all = [];
  for (const logFile of logFiles) {
    const logPath = path.join(LOG_DIR, logFile);
    if (!existsSync(logPath)) continue;
    all.push(`--- ${logFile} ---`);
    const content = await fs.readFile(logPath, 'utf8');
    all.push(...content.split(/\r?\n/).slice(-limit));
  }
  return all.slice(-limit).join('\n');
}

async function createApp() {
  await ensureDirs();
  const app = express();
  app.use(express.json({ limit: '2mb' }));

  app.get('/api/posts', async (req, res) => {
    try { res.json(await dashboardData()); } catch (error) { res.status(500).json({ ok: false, error: error.message }); }
  });

  app.post('/api/posts', async (req, res) => {
    try {
      const posts = await loadPosts();
      const post = validatePostPayload(req.body || {}, posts);
      posts.push(post);
      await savePosts(posts);
      res.json({ ok: true, post });
    } catch (error) { res.status(400).json({ ok: false, error: error.message }); }
  });

  app.put('/api/posts/:index', async (req, res) => {
    try {
      const posts = await loadPosts();
      const index = Number(req.params.index);
      if (!Number.isInteger(index) || index < 0 || index >= posts.length) return res.status(404).json({ ok: false, error: 'post index out of range' });
      const patch = validatePostPayload(req.body || {}, posts, index);
      posts[index] = { ...posts[index], ...patch };
      await savePosts(posts);
      res.json({ ok: true, post: posts[index] });
    } catch (error) { res.status(400).json({ ok: false, error: error.message }); }
  });

  app.delete('/api/posts/:index', async (req, res) => {
    try {
      const posts = await loadPosts();
      const index = Number(req.params.index);
      if (!Number.isInteger(index) || index < 0 || index >= posts.length) return res.status(404).json({ ok: false, error: 'post index out of range' });
      const removed = posts.splice(index, 1)[0];
      await savePosts(posts);
      res.json({ ok: true, removed });
    } catch (error) { res.status(400).json({ ok: false, error: error.message }); }
  });

  app.post('/api/posts/:index/mark-retry', async (req, res) => {
    const posts = await loadPosts();
    const index = Number(req.params.index);
    if (!Number.isInteger(index) || index < 0 || index >= posts.length) return res.status(404).json({ ok: false, error: 'post index out of range' });
    posts[index].status = 'failed_retry';
    posts[index].updated_at = timestampKolkata();
    await savePosts(posts);
    res.json({ ok: true, post: posts[index] });
  });

  app.post('/api/posts/:index/reset-upload', async (req, res) => {
    const posts = await loadPosts();
    const index = Number(req.params.index);
    if (!Number.isInteger(index) || index < 0 || index >= posts.length) return res.status(404).json({ ok: false, error: 'post index out of range' });
    posts[index] = resetUploadFields(posts[index]);
    await savePosts(posts);
    res.json({ ok: true, post: posts[index] });
  });

  app.get('/api/input-files', async (req, res) => res.json({ input_files: await listInputFiles() }));
  app.post('/api/trigger/upload', async (req, res) => res.json(await runSchedulerScript('ig_prepare_uploads.py')));
  app.post('/api/trigger/publish', async (req, res) => res.json(await runSchedulerScript('ig_publish_once.py')));
  app.get('/api/logs', async (req, res) => res.json({ logs: await readLogs() }));

  app.post('/api/git/status', async (req, res) => {
    const child = spawn('git', ['status', '--short'], { cwd: BASE_DIR, shell: true });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (data) => { stdout += data.toString(); });
    child.stderr.on('data', (data) => { stderr += data.toString(); });
    child.on('close', (code) => res.json({ ok: code === 0, stdout, stderr, returncode: code }));
  });

  const vite = await createViteServer({
    root: WEB_UI_DIR,
    server: { middlewareMode: true },
    appType: 'spa',
  });
  app.use(vite.middlewares);
  app.listen(PORT, HOST, () => {
    console.log(`IG Auto Web UI running at http://${HOST}:${PORT}`);
  });
}

createApp().catch((error) => {
  console.error(error);
  process.exit(1);
});
