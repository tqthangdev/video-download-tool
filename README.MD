# Video Download Tool

A desktop video/audio downloader built on **yt-dlp**. Paste a link, preview the video, pick a format (MP4 quality or MP3), add it to a queue and let it run.

The GUI is PyQt6; yt-dlp does the extraction and downloading. The application itself only handles the queue, persistence, format presentation and orchestration — it does not implement site-specific scraping.

## Features

- **Preview before download** — title, thumbnail, duration and every available format for the URL.
- **Format picker** — MP4 qualities (e.g. `360p … 1080p`) and MP3 bitrates, as radio buttons. The actual yt-dlp format id is kept internally; the label is only presentation. Turn on **Auto convert to mp3** to send every pasted or imported link straight to MP3, and **Auto add queue** to queue each pasted link automatically.
- **Queue with a per-session SQLite store** — each session is its own database file, so separate workloads (YouTube vs. an anime site) never mix; a job is one URL + one selected format, so the same video can be queued at several qualities. Jobs survive restarts; on launch the app asks whether to restore the previous session.
- **Sessions** — the **Session** dialog lists one row per session (`[radio] [name] [status]`) with **New**, **Select**, **Edit/Save**, **Remove** and **Remove all** actions. The current session is marked "in use" and its name is shown under **Add Queue**. Removing a session deletes its database file and its scratch folders; a new session's default name is a random id (rename it any time).
- **Pause / resume / delete**, per-job progress (percent, downloaded size, speed, ETA) and clear-done. Interrupted downloads keep their partial data and continue where they left off.
- **Clean output folder** — a job downloads into a hidden `.temp/<session>/<job_id>/` folder inside the output directory and only the finished file is moved out, so the folder never shows half-written files.
- **Batch import** — load a list of URLs from a `.txt` file; the default quality/bitrate from the settings is applied to each.
- **Generic media discovery** — when an extractor returns nothing usable (common on sites and their clones that build the player with plain JavaScript), the page and the player it loads are scanned for media URLs, and the better manifest is used. This needs no per-site configuration.
- **Auto shutdown** when the queue finishes, with a countdown.
- Bilingual UI (Vietnamese / English).

## Requirements

- **Python 3.10+**
- **FFmpeg** — recommended. It is required for MP3 output and for merging video-only + audio streams (typical for 720p and above). Without it those options are not offered.

## Installation

Use the setup script to create a virtual environment (`.venv`) and install the dependencies:

**Linux / macOS:**

```bash
./setup.sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

| Option | Windows equivalent | Description |
| :--- | :--- | :--- |
| `--no-venv` | `-NoVenv` | Install packages into `vendor/` instead of a virtual environment |

### Manual installation

```bash
pip install -r requirements.txt
```

## Running

* **Windows:** double-click `start.bat`
* **Linux / macOS:** run `./start.sh`

Both launchers install the dependencies automatically if they are missing. Or run the app directly:

```bash
# Linux / macOS
.venv/bin/python run.py

# Windows
.venv\Scripts\python.exe run.py
```

## Configuration

`data/config.json` is created next to the app on first run. The **Settings** dialog edits the marked keys:

| Key | In Settings | Description |
| :--- | :--- | :--- |
| `max_workers` | yes | How many downloads run in parallel |
| `download_path` | yes | Default output folder |
| `default_video_quality` | yes | Quality pre-selected in the preview and for batch import (e.g. `720p`) |
| `default_audio_bitrate` | yes | MP3 bitrate pre-selected in the preview and used by **Auto convert to mp3** |
| `language` | yes | UI language (`vi` / `en`) |
| `default_audio_bitrates` | no | Bitrates offered in the MP3 group |
| `request_timeout` | no | Per-request timeout, seconds |
| `download_retry` | no | Retries for failed requests |
| `cookies_file` | no | Path to a Netscape `cookies.txt` for login/age-gated sites |
| `cookies_from_browser` | no | Read cookies from an installed browser (e.g. `chrome`, `firefox`) |

Keys the app no longer knows about are dropped the next time the file is written. Authentication for sites that need it is left to yt-dlp: point `cookies_file` at an exported `cookies.txt`, or let `cookies_from_browser` read them straight from your browser.

The sidebar toggles — **Auto add queue**, **Auto convert to mp3**, **Shutdown when done** — and the last save folder are kept in the app's own settings (`QSettings`), next to `config.json`, not in it. Sessions live in `data/sessions.json`: the registry maps each session's id to its name and remembers the current one, so a restart asks to restore only that session.

Output files are named after the video title (`<title>.mp4` / `<title>.mp3`). Titles longer than the filesystem limit are truncated safely, and spam links embedded in titles are stripped. While a job is running its data stays in `<output>/.temp/<session>/<job_id>/` and is moved into the output folder once complete, so partially downloaded files never appear there; scratch folders left by removed jobs are cleaned up on the next launch.

## Build

**Linux / macOS:**

```bash
chmod +x build.sh
./build.sh
```

**Windows:**

```powershell
.\build.ps1
```
*(If execution is blocked: `Set-ExecutionPolicy -Scope Process Bypass` first)*

Both scripts install the dependencies, package the app with PyInstaller into `dist/VideoDownloadTool/`, and remove temporary files.

## Release

Prebuilt standalone builds (Windows / Linux) are published on [GitHub Releases](https://github.com/tqthangdev/video-download-tool/releases) — no Python installation required. Pushing a `v*` tag triggers the CI build.

The app can check for a newer release itself: the `?` next to the version in the sidebar opens the version dialog, which compares against the latest GitHub release and, on request, downloads and installs it (the app restarts into the new build).

## Disclaimer

Intended for personal use. Respect the terms of service, copyright and rate limits of the sites you use, and only download content you are allowed to. The tool is a graphical front-end for yt-dlp, which does the actual extraction — it does not bypass DRM, and it cannot download from services that yt-dlp does not support.
