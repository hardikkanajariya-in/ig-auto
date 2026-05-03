# IG Auto Workspace

This workspace contains two independent tools:

- `scheduler` for scheduled Instagram publishing
- `reel-editor` for local reel processing with FFmpeg

They do not share input or output folders.

## Scheduler

Run:

```powershell
cd D:\ig-auto\scheduler
python ig_auto_scheduler.py
```

Place scheduler media here:

```text
D:\ig-auto\scheduler\input
```

Scheduler `data.json` lives here:

```text
D:\ig-auto\scheduler\data.json
```

Published, failed, processed files, and logs stay inside the `scheduler` folder.

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
