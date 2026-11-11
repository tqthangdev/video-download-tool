# Video Download Tool

A desktop video/audio downloader built on **yt-dlp**. Paste a link, preview the video, pick a format (MP4 quality or MP3), add it to a queue and let it run.

The GUI is PyQt6; yt-dlp does the extraction and downloading. The application itself only handles the queue, persistence, format presentation and orchestration — it does not implement site-specific scraping.


## Release

Prebuilt standalone builds (Windows / Linux) are published on [GitHub Releases](https://github.com/tqthangdev/video-download-tool/releases) — no Python installation required. Pushing a `v*` tag triggers the CI build.

## Features

- **Preview before download** — title, thumbnail, duration and every available format for the URL.
- **Format picker** — MP4 qualities (e.g. `360p … 1080p`) and MP3 bitrates, as radio buttons. The actual yt-dlp format id is kept internally; the label is only presentation. Turn on **Auto convert to mp3** to send every pasted or imported link straight to MP3, and **Auto add queue** to queue each pasted link automatically.
- **Queue with a per-session SQLite store** — each session is its own database file, so separate workloads (YouTube vs. an anime site) never mix; a job is one URL + one selected format, so the same video can be queued at several qualities. Jobs survive restarts; on launch the app asks whether to restore the previous session.
- **Sessions** — the **Session** dialog lists one row per session (`[radio] [name] [status]`) with **New**, **Select**, **Edit/Save**, **Remove** and **Remove all** actions. The current session is marked "in use" and its name is shown under **Add Queue**. Removing a session deletes its database file and its scratch folders; a new session's default name is a random id (rename it any time).
- **Pause / resume / delete**, per-job progress (percent, downloaded size, speed, ETA) and clear-done. Interrupted downloads keep their partial data and continue where they left off.
- **Clean output folder** — a job downloads into a hidden `.temp/<session>/<job_id>/` folder inside the output directory and only the finished file is moved out, so the folder never shows half-written files.
- **Batch import** — load a list of URLs from a `.txt` file; the default quality/bitrate from the settings is applied to each.
- **Generic media discovery** — when an extractor returns nothing usable (common on sites and their clones that build the player with plain JavaScript), the page and the player it loads are scanned for media URLs, and the better manifest is used. This needs no per-site configuration.
- **JavaScript player fallback** — if the static scan still finds no stream, a hidden browser starts playback, captures the signed manifest, and hands it to yt-dlp. Ads, trackers and popups are filtered out.
- **Fast download** — a direct MP4/WebM that supports Range is fetched by 8 parallel connections (4 MiB chunks); HLS/DASH runs 8 concurrent fragments. Falls back to one yt-dlp stream when the server does not support ranges.
- **Tor proxy** — **Proxy → Auto** (default) keeps the normal network path and starts Tor only for a link that failed as blocked; **On** always uses Tor, **Off** never does. An already-running Tor on `9050`/`9150` is reused.
- **Auto shutdown** when the queue finishes, with a countdown.
- Bilingual UI (Vietnamese / English).

## Requirements

- **Python 3.10+**
- **FFmpeg** — recommended. It is required for MP3 output and for merging video-only + audio streams (typical for 720p and above). Without it those options are not offered.
- **Chrome / Chromium / Edge** — optional; needed for the JavaScript-player browser fallback.

## Installation

Use the setup script to create a virtual environment (`.venv`) and install the dependencies:

**Linux / macOS:**

```bash
./scripts/setup.sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

| Option | Windows equivalent | Description |
| :--- | :--- | :--- |
| `--no-venv` | `-NoVenv` | Install packages into `vendor/` instead of a virtual environment |

### Manual installation

```bash
pip install .
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
| `theme` | yes | UI theme: `system` (follows the OS), `light` or `dark` |
| `network_enabled` | yes | Automatic per-host network fallback (see below) |
| `download_connections` | yes | Parallel connections for direct MP4 / HLS-DASH fragments (default 8; `1` = single stream) |
| `proxy_mode` | menu | **Proxy → Auto / On / Off** (default `auto`) |
| `proxy_url` | yes | Explicit SOCKS/HTTP proxy; overrides Tor when set |
| `tor_timeout` | no | Seconds to wait for an on-demand Tor bootstrap |
| `browser_fallback` | yes | Hidden-browser fallback for JavaScript / iframe players |
| `browser_block_ads` | yes | Block ads, trackers and popups while the browser fallback runs |
| `browser_timeout` | no | Seconds the browser probe may wait for a media request |
| `default_audio_bitrates` | no | Bitrates offered in the MP3 group |
| `request_timeout` | no | Per-request timeout, seconds |
| `download_retry` | no | Retries for failed requests |
| `cookies_file` | no | Path to a Netscape `cookies.txt` for login/age-gated sites |
| `cookies_from_browser` | no | Read cookies from an installed browser (e.g. `chrome`, `firefox`) |

Keys the app no longer knows about are dropped the next time the file is written. Authentication for sites that need it is left to yt-dlp: point `cookies_file` at an exported `cookies.txt`, or let `cookies_from_browser` read them straight from your browser.

The sidebar toggles — **Auto add queue**, **Auto convert to mp3**, **Shutdown when done** — and the last save folder are kept in the app's own settings (`QSettings`), next to `config.json`, not in it. Sessions live in `data/sessions.json`: the registry maps each session's id to its name and remembers the current one, so a restart asks to restore only that session.

### Network fallback

The app runs a small local CONNECT proxy (`core/network`) that yt-dlp and ffmpeg go through. On a hostname whose TLS handshake is silently dropped (a filter that lets TCP connect but never answers), the proxy retries the first flight split into two TLS records (`frag`) instead of sending the ClientHello whole; hosts that already work keep going `direct`. The choice is decided per hostname, learned from the traffic itself (never parsed from yt-dlp output), and remembered for 7 days in `data/network.json`; it is not applied to application errors (404, private video, login required). Turn it off with **Automatic network fallback** in Settings, and clear the learned hosts there too.

### Tor / SOCKS proxy

**Proxy → Auto** is the default. Tor is not started when the app launches: normal links use the direct path (and the local network fallback). If a link fails as blocked — a network error, an HTTP 403/429, a geo-block, or the page cannot be fetched — the app starts Tor on demand, retries that link through it, and remembers the URL so its later download also uses Tor. Other links keep the normal path, even while Tor is running. An already-running Tor on `9050` or `9150` (daemon or Tor Browser) is reused; otherwise the bundled / `PATH` `tor` binary is started with a private DataDirectory in `data/tor/`.

**Proxy → On** starts Tor at launch and uses it for every link. **Proxy → Off** never uses Tor (and stops a Tor the app started). A Tor that was already running is left alone.

yt-dlp gets the same proxy for the metadata extraction and the download, because a signed media URL is bound to the IP that extracted it — using the same exit IP for both avoids 403s. The app's `requests` calls (page scans, size checks) use it too.

Advanced: an explicit proxy in **Settings → Proxy (SOCKS/HTTP)** — or the `YTDLP_PROXY` environment variable — overrides Tor. The format is the usual yt-dlp proxy URL, e.g.:

```
socks5h://127.0.0.1:9050
```

`socks5h` resolves DNS through Tor as well; `socks5` resolves locally. If no Tor binary is available, Auto keeps running the normal path (the blocked link stays failed) and On warns.

### Browser fallback (JavaScript / iframe players)

Some sites never put a media URL in the HTML: an iframe builds the player in JavaScript and asks its own API for a signed manifest. The static scan runs first; if the page has an iframe/player but no manifest, the app drives a real Chrome through **nodriver** (the window minimizes once the page has loaded), with **Playwright** as the fallback. It blocks ads/trackers/popups/images/fonts and media segments, tries to start playback, and captures the `.m3u8`/`.mpd`/`.mp4` request that belongs to the page's main video (related-video previews are ignored). yt-dlp then handles that URL. A resolved browser URL is cached for 5 minutes, so the preview and the download share one browser run; after that (or after a network/HTTP download failure) it is resolved again.

Turn it off with **Browser fallback for JS players**. **Block ads in browser fallback** keeps the best-effort filter: known ad/tracker hosts and paths are blocked, popups are closed, and only the manifest is allowed through. Same-domain ad paths that do not look like ads can still load.

The browser itself is not bundled: nodriver and Playwright both use an installed Chrome/Chromium/Edge (Playwright can also use its own Chromium after `playwright install chromium`). Without one, the app keeps its normal "unsupported" result. The probe adds a few seconds and only runs after the static scan fails.

### Fast download (parallel ranges)

A direct MP4/WebM that advertises byte ranges is downloaded with up to **8 parallel connections** (4 MiB chunks) instead of yt-dlp's single stream; HLS/DASH uses 8 concurrent fragments. Set **Download connections** in Settings (1–16, default 8); `1` keeps the single-stream path. If the server ignores `Range`, the direct file falls back to yt-dlp. Under Tor it is capped at 2 connections.

Many CDNs limit total bandwidth per IP: on the test host, 1, 8 and 32 connections all stayed around 2 MB/s, so more connections is not always faster.

Output files are named after the video title (`<title>.mp4` / `<title>.mp3`). Titles longer than the filesystem limit are truncated safely, and spam links embedded in titles are stripped. While a job is running its data stays in `<output>/.temp/<session>/<job_id>/` and is moved into the output folder once complete, so partially downloaded files never appear there; scratch folders left by removed jobs are cleaned up on the next launch.

## Build

Install the dependencies first (`./scripts/setup.sh` on Linux/macOS, `scripts/setup.ps1` on Windows), then run the build with the project's Python:

**Linux / macOS:**

```bash
.venv/bin/python scripts/build.py
```

**Windows:**

```powershell
.venv\Scripts\python.exe scripts\build.py
```

`scripts/build.py` packages the app with PyInstaller into `dist/VideoDownloadTool/` and removes the temporary files. Pass `--onefile` for a single-file executable.

The external binaries the app needs are **bundled**, so a release only has to be extracted and run — no installs on the user's machine:

- **FFmpeg** (`ffmpeg`/`ffprobe`) — merges video+audio and makes MP3.
- **Deno** — the JavaScript runtime yt-dlp uses to solve YouTube's JS challenges.
- **Tor** — the SOCKS proxy started on demand by **Proxy → Auto** (always by **On**); Tor Expert Bundle with its OpenSSL/libevent libraries and geoip files.

Fetch them once before building:

```bash
python tools/fetch_vendor.py     # downloads FFmpeg + Deno + Tor into vendor/
```

`scripts/build.py` picks them up automatically (and warns if they are missing). The official releases include them; CI runs the fetch before building.

The browser fallback bundles the Playwright Python package but **not** a browser binary: it uses Chrome/Chromium/Edge installed on the host. If none is available, run `playwright install chromium` or install a browser; the app otherwise keeps its normal unsupported result.


## Project layout

```
run.py                  entry point (Qt + asyncio bridge, --update dispatch)
start.sh / start.bat    launchers (run.py + scripts/setup.sh if needed)
version.json            the running build's version
core/                   headless backend (no Qt except engine.py)
  download/             yt-dlp pipeline + browser media probe (extraction, download, formats)
  storage/              queue persistence (SQLite job store + session registry)
  network/              local CONNECT proxy fallback + Tor SOCKS manager
  updater/              version check + self-update
gui/
  app/                  MainWindow and its wiring
  panels/               the two panels, the preview and the queue delegate
  dialogs/              modal dialogs
  common/               theme (palettes), widget factories, helpers
assets/                 bundled assets, grouped by purpose:
  app/                    window/taskbar icons (icon.png, icon.ico)
  icons/                  indicator SVGs (+ -light variants):
    checkbox/ radio/        QCheckBox / QRadioButton indicators
    spin/                   QComboBox / QSpinBox / scrollbar arrows
    help/                   "?" help button
    trash.svg               queue row delete icon
  images/                 loading.gif spinner
data/ logs/             runtime state (config, sessions, learned hosts, logs)
docs/                   this README, flow.md (behaviour spec), feedback.md
scripts/                build.py + setup.sh / setup.ps1 (dev + first-run install)
tools/                  standalone diagnostics (frag_test, run_proxy, fetch_vendor)
```


## Disclaimer

Intended for personal use. Respect the terms of service, copyright and rate limits of the sites you use, and only download content you are allowed to. The tool is a graphical front-end for yt-dlp, which does the actual extraction — it does not bypass DRM, and it cannot download from services that yt-dlp does not support.
