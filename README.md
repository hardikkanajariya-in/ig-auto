# IG Auto Workspace

This workspace contains two independent tools:

- `scheduler` for scheduled Instagram publishing
- `reel-editor` for local reel processing with FFmpeg

They do not share input or output folders.

## Scheduler

The scheduler is now split into:

- local preparation/upload
- GitHub Actions based publishing every 5 minutes

Keep [scheduler/ig_auto_scheduler.py](/d:/ig-auto/scheduler/ig_auto_scheduler.py:1) as a backup of the older monolithic flow. The active files are:

- [scheduler/ig_common.py](/d:/ig-auto/scheduler/ig_common.py:1)
- [scheduler/ig_prepare_uploads.py](/d:/ig-auto/scheduler/ig_prepare_uploads.py:1)
- [scheduler/ig_publish_once.py](/d:/ig-auto/scheduler/ig_publish_once.py:1)
- [.github/workflows/instagram-publish.yml](/d:/ig-auto/.github/workflows/instagram-publish.yml:1)

### Local Preparation

Run locally to upload pending media to Cloudinary:

```powershell
cd D:\ig-auto\scheduler
python ig_prepare_uploads.py
```

Place scheduler media here:

```text
D:\ig-auto\scheduler\input
```

Scheduler `data.json` lives here:

```text
D:\ig-auto\scheduler\data.json
```

After local preparation:

1. Commit the updated `scheduler\data.json`
2. Push it to GitHub
3. GitHub Actions will publish due posts every 5 minutes

`publish_at` values in `scheduler\data.json` are interpreted in `Asia/Kolkata` time.

The preparation script:

- uploads only posts that still need Cloudinary upload
- does not create Instagram containers
- does not publish to Instagram
- does not delete local media

The GitHub publish script:

- runs once and exits
- creates the Instagram container only at publish time
- publishes only due posts that already have a stored `cloudinary_url`
- does not require local media files on GitHub

Because the Cloudinary URL is saved into `scheduler\data.json`, GitHub Actions can publish later without your original media file being present on the runner.

### Required GitHub Secrets

Configure these repository secrets:

- `IG_USER_ID`
- `IG_ACCESS_TOKEN`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

### GitHub Workflow

The workflow is [instagram-publish.yml](/d:/ig-auto/.github/workflows/instagram-publish.yml:1).

It:

- runs every 5 minutes
- also supports manual `workflow_dispatch`
- runs `python ig_publish_once.py` inside `scheduler`
- commits back `scheduler/data.json` when statuses change

## Local Web UI

The local control panel is built with Node.js, Express, and Vite. It does not use Flask.

Run:

```powershell
cd D:\ig-auto\web-ui
npm install
npm run dev
```

Then open:

```text
http://127.0.0.1:5050
```

The UI can:

- read `scheduler/data.json`
- read files from `scheduler/input`
- show pending, uploaded, published, failed, missing, outdated, and unsynced statuses
- create new records in `data.json`
- edit/delete/reset records
- manually trigger upload preparation by running `scheduler/ig_prepare_uploads.py`
- manually trigger one publish check by running `scheduler/ig_publish_once.py`
- show recent scheduler logs

The web UI is for local personal use only. It binds to localhost and should not be deployed publicly.

## Reel Editor

Run:

```powershell
cd D:\ig-auto\reel-editor
python process_reels.py
```

Place reel editor input files here:

```text
D:\ig-auto\reel-editor\input
```

Processed reel outputs are written here:

```text
D:\ig-auto\reel-editor\output
```

The reel editor logo asset is kept here:

```text
D:\ig-auto\reel-editor\assets\logo.png
```

## Environment File

`.env` stays at the workspace root:

```text
D:\ig-auto\.env
```

Both scripts now try to load `.env` from:

- their own folder
- the parent root folder

That keeps the root `.env` working after moving the scripts into subfolders.
