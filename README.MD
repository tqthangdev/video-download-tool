# Video Download Tool

A desktop video/audio downloader built on **yt-dlp**. Paste a link, preview the video, pick a format (MP4 quality or MP3), add it to a queue and let it run.

The GUI is PyQt6; yt-dlp does the extraction and downloading. The application itself only handles the queue, persistence, format presentation and orchestration — it does not implement site-specific scraping.

## Features

- **Preview before download** — title, thumbnail, duration and every available format for the URL.
- **Format picker** — MP4 qualities (e.g. `360p … 1080p`) and MP3 bitrates, as radio buttons. The actual yt-dlp format id is kept internally; the label is only presentation.
- **Queue with a SQLite job store** — a job is one URL + one selected format, so the same video can be queued at several qualities. Jobs survive restarts and are restored on the next launch.
- **Pause / resume / delete**, per-job progress (percent, downloaded size, speed, ETA) and clear-done.
- **Batch import** — load a list of URLs from a `.txt` file; the default quality/bitrate from the settings is applied to each.
- **Generic media discovery** — when an extractor returns nothing usable (common on sites and their clones that build the player with plain JavaScript), the page and the player it loads are scanned for media URLs, and the better manifest is used. This needs no per-site configuration.
- **Optional Gemini title shortening** — long titles can be shortened by Gemini into filename-friendly labels. Requires your own API key; without a key (or when the model refuses) the original title is kept.
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

`data/config.json` is created next to the app on first run. Most keys are editable from the app's **Settings** dialog:

| Key | In Settings | Description |
| :--- | :--- | :--- |
| `max_workers` | yes | How many downloads run in parallel |
| `download_path` | yes | Default output folder |
| `default_video_quality` | yes | Pre-selected quality when importing from a file (e.g. `720p`) |
| `default_audio_bitrate` | yes | Pre-selected MP3 bitrate when importing from a file |
| `prefer` | yes | Which kind of format is pre-selected (`video` or `audio`) |
| `gemini_api` | yes | Gemini API key for optional title shortening; empty disables it |
| `language` | yes | UI language (`vi` / `en`) |
| `default_audio_bitrates` | no | Bitrates offered in the MP3 group |
| `request_timeout` | no | Per-request timeout, seconds |
| `download_retry` | no | Retries for failed requests |
| `cookies_file` | no | Path to a Netscape `cookies.txt` for login/age-gated sites |
| `cookies_from_browser` | no | Read cookies from an installed browser (e.g. `chrome`, `firefox`) |

Authentication for sites that need it is left to yt-dlp: point `cookies_file` at an exported `cookies.txt`, or let `cookies_from_browser` read them straight from your browser.

Output files are named after the video title (`<title>.mp4` / `<title>.mp3`). Titles longer than the filesystem limit are truncated safely, and spam links embedded in titles are stripped.

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

Both scripts install the dependencies, package the app with PyInstaller into `dist/VideoDownloadTool/`, and remove temporary files. Tagged pushes (`v*`) build and publish both platforms via `.github/workflows/build.yml`.

## Disclaimer

Intended for personal use. Respect the terms of service, copyright and rate limits of the sites you use, and only download content you are allowed to. The tool is a graphical front-end for yt-dlp, which does the actual extraction — it does not bypass DRM, and it cannot download from services that yt-dlp does not support.
